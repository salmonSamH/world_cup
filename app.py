import threading
import time
from dash import Dash, html, clientside_callback, Input, Output, State, dcc, dash
import dash_ag_grid as dag
import requests
import string
import pandas as pd
import datetime
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import os
# app.py, callbacks.py, background.py — all import from the same place
from state import cache, cache_lock

app = Dash(__name__, external_stylesheets=[
    'https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&display=swap'
])
server = app.server

load_dotenv()  # only does something if .env exists locally; harmless if not
api_key = os.environ.get("API_KEY")  # use .get(), not [...]
still_waiting = False

headers = {'x-apisports-key': api_key}
payload = {'league': 1, 'season': 2026}
column_defs = [
    {"field": "team",   "headerName": "Team", "width": 200, "headerClass": "ag-left-aligned-header", "cellStyle": {"textAlign": "left"}, "cellRenderer": "TeamRenderer"},
    {"field": "points",  "headerName": "Pts", "cellStyle": {"fontWeight": "bold"}},
    {"field": "form",  "headerName": "Form", "width": 150, "cellRenderer": "FormRenderer"},
    {"field": "played",  "headerName": "MP"},
    {"field": "win",    "headerName": "W"},
    {"field": "draw",    "headerName": "D"},
    {"field": "lose",    "headerName": "L"},
    {"field": "goalsFor",  "headerName": "GF"},
    {"field": "goalsAgainst",  "headerName": "GA"},
    {"field": "goalsDiff",  "headerName": "GD"}
]
default_col_def = {"width": 55, "cellStyle": {"textAlign": "center"}, "headerClass": "center-header", "resizable": False}
get_row_style = {
                    "styleConditions": 
                    [
                        {
                            "condition": "params.data.advances === true",
                            "style": {"borderLeft": "3px solid #2a9d8f"},
                        },
                        {
                            "condition": "params.data.advances === false",
                            "style": {"borderLeft": "3px solid #ffffff"},
                        }
                    ]
                }
dash_grid_options = {
    "domLayout": "autoHeight",
    "suppressFieldDotNotation": True,
}
style = {"height": None}
venues = {"East Rutherford": "New York New Jersey", "Miami Gardens": "Miami", "Arlington": "Dallas", "Santa Clara": "San Francisco Bay Area", "Inglewood": "Los Angeles"}
rounds = {"Group Stage - 1": "First Stage", "Group Stage - 2": "Second Stage", "Group Stage - 3": "Third Stage"}
column_defs_fixtures = [
    {'field': 'date', 'headerName': 'Date', "width": 120},
    {'field': 'time', 'headerName': 'Time (PDT)', "width": 120},
    {'field': 'city', 'headerName': 'Location'},
    {'field': 'round', 'headerName': 'Round'},
    {'field': 'status', 'headerName': 'Status', "width": 150},
    {'field': 'home', 'headerName': '', "cellRenderer": "HomeRenderer"},
    {'field': 'score', 'headerName': '', "width": 100, "enableCellChangeFlash": True},
    {'field': 'away', 'headerName': '', "cellRenderer": "AwayRenderer"},
]
default_col_def_fixtures = {"width": 200, "cellStyle": {"textAlign": "center"}, "headerClass": "center-header", "resizable": False}
dash_grid_options_fixtures = {
    "suppressFieldDotNotation": True,
}
style_fixtures = {"height": "400px"}
ADDED = False

# ── Background worker ──────────────────────────────────────────────
def fetch_and_process():
    while True:
        response = requests.get(url = 'https://v3.football.api-sports.io/standings', headers = headers, params = payload)
        standings = response.json().get('response')[0].get('league').get('standings')
        t8_3rd = pd.json_normalize(standings[-1][:-4])

        standings_rows = []

        for idx, standing in enumerate(standings[:-1]):
            table = pd.json_normalize(standing).set_index('rank')
            table['advances'] = (table.index <= 2) | (table['team.id'].isin(t8_3rd["team.id"]))
            table['form'] = table['form'].apply(lambda x: x[:5][::-1] + (5 - len(x)) * 'N')
            table = table[['advances', 'team.id', 'team.logo', 'team.name', 'all.played', 'all.win', 'all.draw', 'all.lose', 'all.goals.for', 'all.goals.against', 'goalsDiff', 'points', 'form']]
            table.columns = ['advances', 'id', 'logo', 'team', 'played', 'win', 'draw', 'lose', 'goalsFor', 'goalsAgainst', 'goalsDiff', 'points', 'form']
            table['group'] = string.ascii_uppercase[idx]
            table = table.to_dict('records')
            standings_rows.append(table)

        teams = pd.json_normalize([team for group in standings_rows for team in group]).set_index('id')

        response = requests.get(url = 'https://v3.football.api-sports.io/fixtures', headers = headers, params = payload)
        fixtures = pd.json_normalize(response.json().get("response"))
        fixtures = fixtures[['fixture.id', 'fixture.timestamp', 'fixture.venue.name', 'fixture.venue.city', 'fixture.status.long', 'fixture.status.short', 'fixture.status.elapsed', 'fixture.status.extra', 'league.name', 'league.round', 'teams.home.id', 'teams.home.name', 'teams.home.logo', 'teams.away.id', 'teams.away.name', 'teams.away.logo', 'goals.home', 'goals.away']]
        fixtures.columns = ['id','timestamp', 'venue', 'city', 'status_long', 'status_short', 'elapsed', 'extra', 'league', 'round', 'home_id', 'home', 'home_logo', 'away_id', 'away', 'away_logo', 'home_goals', 'away_goals']
        fixtures = fixtures.sort_values('timestamp').reset_index(drop=True)
        fixtures['date'] = fixtures['timestamp'].apply(lambda x: datetime.datetime.fromtimestamp(x).astimezone(ZoneInfo("America/Los_Angeles")).strftime('%Y-%m-%d'))
        fixtures['time'] = fixtures['timestamp'].apply(lambda x: datetime.datetime.fromtimestamp(x).astimezone(ZoneInfo("America/Los_Angeles")).strftime('%H:%M'))
        fixtures['score'] = fixtures.apply(lambda x: str(round(x['home_goals'])) + ' - ' + str(round(x['away_goals'])) if pd.notna(x['home_goals']) and pd.notna(x['away_goals']) else None, axis=1)
        fixtures['city'] = fixtures['city'].apply(lambda x: x if x not in venues.keys() else venues[x])
        fixtures['round'] = fixtures['round'].apply(lambda x: x if x not in rounds.keys() else rounds[x])
        fixtures['group'] = fixtures['home_id'].apply(lambda x: str(teams.loc[x, 'group']))
        fixtures['round'] = fixtures.apply(lambda x: x['round'] if 'Stage' not in x['round'] else 'Group ' + x['group'] + ', ' + x['round'], axis = 1)
        fixtures['status'] = fixtures.apply(lambda x: x['status_short'] + " " + str(round(x['elapsed'])) + "'" if x['status_short'] in ['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'] else x['status_short'], axis = 1)
        fixtures['status'] = fixtures.apply(lambda x: x['status'] + " + " + str(round(x['extra'])) + "'" if x['status_short'] in ['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'] and pd.notna(x['extra']) else x['status'], axis = 1)
        fixtures = fixtures.astype(object).where(pd.notnull(fixtures), None)
        fixtures_records = fixtures.to_dict('records')

        # print(fixtures['group'].unique())

        first_upcoming = max(fixtures[fixtures['status_short'] != 'FT'].index.min() - 4, 0)
        
        with cache_lock:
            cache["standings_rows"] = standings_rows
            cache["fixtures"] = fixtures_records
            cache["first_upcoming"] = first_upcoming
            cache["last_updated"] = time.time()

        time.sleep(60)  # poll interval

# Start worker once at startup
worker = threading.Thread(target=fetch_and_process, daemon=True)
worker.start()

@app.callback(
    Output("scroll-target-store", "data"),
    Input("scroll-trigger", "n_intervals"),
)
def init_scroll(_):
    with cache_lock:
        return cache.get("first_upcoming", 0)
clientside_callback(
    f"""
    function(n) {{
        if (!n) return null;
        setTimeout(function() {{
            var api = dash_ag_grid.getApiAsync("fixtures-grid");
            api.then(function(gridApi) {{
                gridApi.ensureIndexVisible(n, "top");
            }});
        }}, 100);
        return null;
    }}
    """,
    Output("scroll-dummy", "children"),
    Input("scroll-target-store", "data"),
)

ROUNDS = [{"name":"Round of 32", "matches": [
    {"team1": "home", "team2": "away", "info": "74"}, {"team1": "home", "team2": "away", "info": "77"}, {"team1": "home", "team2": "away", "info": "73"}, {"team1": "home", "team2": "away", "info": "75"},
    {"team1": "home", "team2": "away", "info": "83"}, {"team1": "home", "team2": "away", "info": "84"}, {"team1": "home", "team2": "away", "info": "81"}, {"team1": "home", "team2": "away", "info": "82"},
    {"team1": "home", "team2": "away", "info": "76"}, {"team1": "home", "team2": "away", "info": "78"}, {"team1": "home", "team2": "away", "info": "79"}, {"team1": "home", "team2": "away", "info": "80"},
    {"team1": "home", "team2": "away", "info": "86"}, {"team1": "home", "team2": "away", "info": "88"}, {"team1": "home", "team2": "away", "info": "85"}, {"team1": "home", "team2": "away", "info": "87"}
]}, {"name": "Round of 16", "matches": [
    {"team1": "home", "team2": "away", "info": "89"}, {"team1": "home", "team2": "away", "info": "90"}, {"team1": "home", "team2": "away", "info": "93"}, {"team1": "home", "team2": "away", "info": "94"},
    {"team1": "home", "team2": "away", "info": "91"}, {"team1": "home", "team2": "away", "info": "92"}, {"team1": "home", "team2": "away", "info": "95"}, {"team1": "home", "team2": "away", "info": "96"}
]}, {"name": "Quarterfinals", "matches": [
    {"team1": "home", "team2": "away", "info": "97"}, {"team1": "home", "team2": "away", "info": "98"}, {"team1": "home", "team2": "away", "info": "99"}, {"team1": "home", "team2": "away", "info": "100"}
]}, {"name": "Semifinals", "matches": [
    {"team1": "home", "team2": "away", "info": "101"}, {"team1": "home", "team2": "away", "info": "102"}
]}, {"name": "Finals", "matches": [
    {"team1": "home", "team2": "away", "info": "104"}
]}, {"name": "Third Place", "matches": [
    {"team1": "home", "team2": "away", "info": "103"}
]}]
app.layout = html.Div([
    html.H1("World Cup Tracker", style={"fontFamily": "Inter, sans-serif"}),
    html.P("My website for following the World Cup, inspired in part by Google's World Cup widget.", style={"fontFamily": "Inter, sans-serif"}),
    dcc.Interval(id="scroll-trigger", interval=1000, max_intervals=2),
    html.Div(id="scroll-dummy", style={"display": "none"}),
    dcc.Store(id="scroll-target-store"),
    dcc.Store(id="fixtures-rows"),
    dcc.Store(id="group-a-data"),
    dcc.Store(id="group-b-data"),
    dcc.Store(id="group-c-data"),
    dcc.Store(id="group-d-data"),
    dcc.Store(id="group-e-data"),
    dcc.Store(id="group-f-data"),
    dcc.Store(id="group-g-data"),
    dcc.Store(id="group-h-data"),
    dcc.Store(id="group-i-data"),
    dcc.Store(id="group-j-data"),
    dcc.Store(id="group-k-data"),
    dcc.Store(id="group-l-data"),
    dcc.Interval(id="tick", interval=5_000),  # adjust interval as needed
    dcc.Tabs(id="tabs", value="tab-1", children=[
        dcc.Tab(label="Fixtures", value="tab-1", style={"fontFamily": "Inter, sans-serif"}, children=[
            html.H2("Fixtures", style={"fontFamily": "Inter, sans-serif"}),
            dag.AgGrid(id="fixtures-grid", rowData=[], columnDefs=column_defs_fixtures, defaultColDef = default_col_def_fixtures, getRowId="params.data.id"),
        ]),
        dcc.Tab(label="Standings", value="tab-2", style={"fontFamily": "Inter, sans-serif"}, children=[
            html.H2("Standings", style={"fontFamily": "Inter, sans-serif"}),
            html.Div(
                [
                    html.Div([
                        html.H3("Group A", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-a", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group B", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-b", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group C", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-c", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group D", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-d", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group E", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-e", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group F", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-f", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group G", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-g", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group H", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-h", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group I", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-i", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group J", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-j", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group K", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-k", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group L", style={"fontFamily": "Inter, sans-serif"}),
                        dag.AgGrid(id="group-l", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                ], 
                style = {
                    "display": "grid",
                    "gridTemplateColumns": "repeat(2, 1fr)",
                    "gap": "32px",
                    "minHeight": "600px"
                }, 
                id="standings-grid"
            )
        ]),
        dcc.Tab(label="Bracket", value="tab-3", style={"fontFamily": "Inter, sans-serif"}, children=[
            html.H2("Bracket", style={"fontFamily": "Inter, sans-serif"}),
            html.Div(className="bracket", children=[
                html.Div(id="round-of-32", className="round", children=[
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-74"), html.Div(children = [], className="away", id="away-74"), html.Div(children = [], className="info", id="info-74"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-77"), html.Div(children = [], className="away", id="away-77"), html.Div(children = [], className="info", id="info-77"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-73"), html.Div(children = [], className="away", id="away-73"), html.Div(children = [], className="info", id="info-73"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-75"), html.Div(children = [], className="away", id="away-75"), html.Div(children = [], className="info", id="info-75"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-83"), html.Div(children = [], className="away", id="away-83"), html.Div(children = [], className="info", id="info-83"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-84"), html.Div(children = [], className="away", id="away-84"), html.Div(children = [], className="info", id="info-84"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-81"), html.Div(children = [], className="away", id="away-81"), html.Div(children = [], className="info", id="info-81"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-82"), html.Div(children = [], className="away", id="away-82"), html.Div(children = [], className="info", id="info-82"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-76"), html.Div(children = [], className="away", id="away-76"), html.Div(children = [], className="info", id="info-76"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-78"), html.Div(children = [], className="away", id="away-78"), html.Div(children = [], className="info", id="info-78"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-79"), html.Div(children = [], className="away", id="away-79"), html.Div(children = [], className="info", id="info-79"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-80"), html.Div(children = [], className="away", id="away-80"), html.Div(children = [], className="info", id="info-80"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-86"), html.Div(children = [], className="away", id="away-86"), html.Div(children = [], className="info", id="info-86"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-88"), html.Div(children = [], className="away", id="away-88"), html.Div(children = [], className="info", id="info-88"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-85"), html.Div(children = [], className="away", id="away-85"), html.Div(children = [], className="info", id="info-85"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-87"), html.Div(children = [], className="away", id="away-87"), html.Div(children = [], className="info", id="info-87")
                    ]) 
                ]),
                html.Div(children=[
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                ],id="32-to-16-before", className="connector-column"),
                html.Div(children=[
                    html.Div(className="connector-vertical-4"),
                    html.Div(className="connector-vertical-4"),
                    html.Div(className="connector-vertical-4"),
                    html.Div(className="connector-vertical-4"),
                    html.Div(className="connector-vertical-4"),
                    html.Div(className="connector-vertical-4"),
                    html.Div(className="connector-vertical-4"),
                    html.Div(className="connector-vertical-4"),
                ],id="32-to-16-middle", className="connector-column-vertical"),
                html.Div(children=[
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                ],id="32-to-16-after", className="connector-column"),
                html.Div(id="round-of-16", className="round", children=[
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-89"), html.Div(children = [], className="away", id="away-89"), html.Div(children = [], className="info", id="info-89"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-90"), html.Div(children = [], className="away", id="away-90"), html.Div(children = [], className="info", id="info-90"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-93"), html.Div(children = [], className="away", id="away-93"), html.Div(children = [], className="info", id="info-93"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-94"), html.Div(children = [], className="away", id="away-94"), html.Div(children = [], className="info", id="info-94"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-91"), html.Div(children = [], className="away", id="away-91"), html.Div(children = [], className="info", id="info-91"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-92"), html.Div(children = [], className="away", id="away-92"), html.Div(children = [], className="info", id="info-92"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-95"), html.Div(children = [], className="away", id="away-95"), html.Div(children = [], className="info", id="info-95"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-96"), html.Div(children = [], className="away", id="away-96"), html.Div(children = [], className="info", id="info-96"),
                    ])
                ]),
                html.Div(children=[
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                ],id="16-to-quarters-before", className="connector-column"),
                html.Div(children=[
                    html.Div(className="connector-vertical-3"),
                    html.Div(className="connector-vertical-3"),
                    html.Div(className="connector-vertical-3"),
                    html.Div(className="connector-vertical-3"),
                ],id="16-to-quarters-middle", className="connector-column-vertical"),
                html.Div(children=[
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector")
                ],id="16-to-quarters-after", className="connector-column"),
                html.Div(id="quarterfinals", className="round", children=[
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-97"), html.Div(children = [], className="away", id="away-97"), html.Div(children = [], className="info", id="info-97"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-98"), html.Div(children = [], className="away", id="away-98"), html.Div(children = [], className="info", id="info-98"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-99"), html.Div(children = [], className="away", id="away-99"), html.Div(children = [], className="info", id="info-99"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-100"), html.Div(children = [], className="away", id="away-100"), html.Div(children = [], className="info", id="info-100"),
                    ]),
                ]),
                html.Div(children=[
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector"),
                    html.Div(className="connector")
                ],id="quarters-to-semis-before", className="connector-column"),
                html.Div(children=[
                    html.Div(className="connector-vertical-2"),
                    html.Div(className="connector-vertical-2"),
                ],id="quarters-to-semis-middle", className="connector-column-vertical"),
                html.Div(children=[
                    html.Div(className="connector"),
                    html.Div(className="connector")
                ],id="quarters-to-semis-after", className="connector-column"),
                html.Div(id="semifinals", className="round", children=[
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-101"), html.Div(children = [], className="away", id="away-101"), html.Div(children = [], className="info", id="info-101"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-102"), html.Div(children = [], className="away", id="away-102"), html.Div(children = [], className="info", id="info-102"),
                    ]),
                ]),
                html.Div(children=[
                    html.Div(className="connector"),
                    html.Div(className="connector")
                ],id="semis-to-finals-before", className="connector-column"),
                html.Div(children=[
                    html.Div(className="connector-vertical-1")
                ],id="semis-to-finals-middle", className="connector-column-vertical"),
                html.Div(children=[
                    html.Div(className="connector")
                ],id="semis-to-finals-after", className="connector-column"),
                html.Div(id="finals", className="round", children=[
                    html.Div(className="match-dummy"),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-104"), html.Div(children = [], className="away", id="away-104"), html.Div(children = [], className="info", id="info-104"),
                    ]),
                    html.Div(className="match", children=[
                         html.Div(children = [], className="home", id="home-103"), html.Div(children = [], className="away", id="away-103"), html.Div(children = [], className="info", id="info-103"),
                    ]),
                ])
            ])
        ]),
    ]),
    html.Small(children = "", id="last-updated-display", style={"color": "gray", "fontFamily": "Inter, sans-serif"})
], id = 'whole-thing')

@app.callback(
    Output("fixtures-grid", "rowTransaction"),
    Output("group-a", "rowTransaction"), 
    Output("group-b", "rowTransaction"), 
    Output("group-c", "rowTransaction"), 
    Output("group-d", "rowTransaction"), 
    Output("group-e", "rowTransaction"), 
    Output("group-f", "rowTransaction"), 
    Output("group-g", "rowTransaction"), 
    Output("group-h", "rowTransaction"), 
    Output("group-i", "rowTransaction"), 
    Output("group-j", "rowTransaction"), 
    Output("group-k", "rowTransaction"), 
    Output("group-l", "rowTransaction"),  
    Output("last-updated-display", "children"),
    Output("fixtures-rows", "data"),
    Output("group-a-data", "data"),
    Output("group-b-data", "data"),
    Output("group-c-data", "data"),
    Output("group-d-data", "data"),
    Output("group-e-data", "data"),
    Output("group-f-data", "data"),
    Output("group-g-data", "data"),
    Output("group-h-data", "data"),
    Output("group-i-data", "data"),
    Output("group-j-data", "data"),
    Output("group-k-data", "data"),
    Output("group-l-data", "data"),
    Output("home-74", "children"),
    Output("away-74", "children"),
    Output("info-74", "children"),
    Output("home-77", "children"),
    Output("away-77", "children"),
    Output("info-77", "children"),
    Output("home-73", "children"),
    Output("away-73", "children"),
    Output("info-73", "children"),
    Output("home-75", "children"),
    Output("away-75", "children"),
    Output("info-75", "children"),
    Output("home-83", "children"),
    Output("away-83", "children"),
    Output("info-83", "children"),
    Output("home-84", "children"),
    Output("away-84", "children"),
    Output("info-84", "children"),
    Output("home-81", "children"),
    Output("away-81", "children"),
    Output("info-81", "children"),
    Output("home-82", "children"),
    Output("away-82", "children"),
    Output("info-82", "children"),
    Output("home-76", "children"),
    Output("away-76", "children"),
    Output("info-76", "children"),
    Output("home-78", "children"),
    Output("away-78", "children"),
    Output("info-78", "children"),
    Output("home-79", "children"),
    Output("away-79", "children"),
    Output("info-79", "children"),
    Output("home-80", "children"),
    Output("away-80", "children"),
    Output("info-80", "children"),
    Output("home-86", "children"),
    Output("away-86", "children"),
    Output("info-86", "children"),
    Output("home-88", "children"),
    Output("away-88", "children"),
    Output("info-88", "children"),
    Output("home-85", "children"),
    Output("away-85", "children"),
    Output("info-85", "children"),
    Output("home-87", "children"),
    Output("away-87", "children"),
    Output("info-87", "children"),
    Output("home-89", "children"),
    Output("away-89", "children"),
    Output("info-89", "children"),
    Output("home-90", "children"),
    Output("away-90", "children"),
    Output("info-90", "children"),
    Output("home-93", "children"),
    Output("away-93", "children"),
    Output("info-93", "children"),
    Output("home-94", "children"),
    Output("away-94", "children"),
    Output("info-94", "children"),
    Output("home-91", "children"),
    Output("away-91", "children"),
    Output("info-91", "children"),
    Output("home-92", "children"),
    Output("away-92", "children"),
    Output("info-92", "children"),
    Output("home-95", "children"),
    Output("away-95", "children"),
    Output("info-95", "children"),
    Output("home-96", "children"),
    Output("away-96", "children"),
    Output("info-96", "children"),
    Output("home-97", "children"),
    Output("away-97", "children"),
    Output("info-97", "children"),
    Output("home-98", "children"),
    Output("away-98", "children"),
    Output("info-98", "children"),
    Output("home-99", "children"),
    Output("away-99", "children"),
    Output("info-99", "children"),
    Output("home-100", "children"),
    Output("away-100", "children"),
    Output("info-100", "children"),
    Output("home-101", "children"),
    Output("away-101", "children"),
    Output("info-101", "children"),
    Output("home-102", "children"),
    Output("away-102", "children"),
    Output("info-102", "children"),
    Output("home-103", "children"),
    Output("away-103", "children"),
    Output("info-103", "children"),
    Output("home-104", "children"),
    Output("away-104", "children"),
    Output("info-104", "children"),
    Input("tick", "n_intervals"),
    State("fixtures-rows", "data"),
    State("group-a-data", "data"),
    State("group-b-data", "data"),
    State("group-c-data", "data"),
    State("group-d-data", "data"),
    State("group-e-data", "data"),
    State("group-f-data", "data"),
    State("group-g-data", "data"),
    State("group-h-data", "data"),
    State("group-i-data", "data"),
    State("group-j-data", "data"),
    State("group-k-data", "data"),
    State("group-l-data", "data"),
)
def refresh_grids(n, previous_rows, a, b, c, d, e, f, g, h, i, j, k, l):
    global still_waiting
    try:
        with cache_lock:
            standings_rows = cache["standings_rows"]
            fixtures = cache["fixtures"]
            ts = cache["last_updated"]

        if standings_rows is None or fixtures is None:
            no_update = dash.no_update
            waiting_text = "Waiting for first update..."
            if still_waiting:
                waiting_text = "Still waiting for first update..."
            else:
                still_waiting = True
            result = [no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, waiting_text, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update]
            result.extend([no_update] * 96)
            return tuple(result)
        
        last_updated = f"Last updated: {time.strftime('%H:%M:%S', time.localtime(ts))} UTC"
        
        previous_dict = {r["id"]: r for r in (previous_rows or [])}
        to_add, to_update = [], []
        for row in fixtures:
            if row["id"] not in previous_dict:
                to_add.append(row)
            elif previous_dict[row["id"]] != row:
                to_update.append(row)
        
        fixtures_update = {"add": to_add, "update": to_update}
        if len(to_add) == 0 and len(to_update) == 0:
            fixtures_update = dash.no_update

        knockout_fixtures = pd.DataFrame.from_records(fixtures).reindex(index = [74, 77, 73, 75, 83, 84, 81, 82, 76, 78, 79, 80, 86, 88, 85, 87, 89, 90, 93, 94, 91, 92, 95, 96, 97, 98, 99, 100, 101, 102, 104, 103], columns = ['id', 'date', 'time', 'city', 'round', 'status', 'home_id', 'home', 'home_logo', 'away_id', 'away', 'away_logo', 'home_goals', 'away_goals'])
        print(knockout_fixtures)

        result = [fixtures_update, updates(a, standings_rows[0]), updates(b, standings_rows[1]), updates(c, standings_rows[2]), updates(d, standings_rows[3]), updates(e, standings_rows[4]), updates(f, standings_rows[5]), updates(g, standings_rows[6]), updates(h, standings_rows[7]), updates(i, standings_rows[8]), updates(j, standings_rows[9]), updates(k, standings_rows[10]), updates(l, standings_rows[11]), last_updated, fixtures, standings_rows[0], standings_rows[1], standings_rows[2], standings_rows[3], standings_rows[4], standings_rows[5], standings_rows[6], standings_rows[7], standings_rows[8], standings_rows[9], standings_rows[10], standings_rows[11]]
        result.extend(["TBD"] * 96)
        return tuple(result)
    except Exception as e:
        import traceback
        print(traceback.format_exc())   # shows in server logs
        raise

def updates(old, new):
    previous_dict = {r["id"]: r for r in (old or [])}
    to_add, to_update = [], []
    for row in new:
        if row["id"] not in previous_dict:
            to_add.append(row)
        elif previous_dict[row["id"]] != row:
            to_update.append(row)
    
    changes = {"add": to_add, "update": to_update}
    if len(to_add) == 0 and len(to_update) == 0:
        changes = dash.no_update
    return changes

if __name__ == "__main__":
    app.run(debug=True)
