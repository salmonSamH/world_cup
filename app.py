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

app = Dash(__name__)
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
        try:
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
            fixtures['group'] = fixtures['home_id'].apply(lambda x: teams.loc[x, 'group'])
            fixtures['round'] = fixtures.apply(lambda x: x['round'] if pd.isna(x['group']) or 'Stage' not in x['round'] else 'Group ' + x['group'] + ', ' + x['round'], axis = 1)
            fixtures['status'] = fixtures.apply(lambda x: x['status_short'] + " " + str(round(x['elapsed'])) + "'" if x['status_short'] in ['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'] else x['status_short'], axis = 1)
            fixtures['status'] = fixtures.apply(lambda x: x['status'] + " + " + str(round(x['extra'])) + "'" if x['status_short'] in ['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'] and pd.notna(x['extra']) else x['status'], axis = 1)
            fixtures = fixtures.astype(object).where(pd.notnull(fixtures), None)
            fixtures_records = fixtures.to_dict('records')

            first_upcoming = max(fixtures[fixtures['status_short'] != 'FT'].index.min() - 4, 0)
            
            with cache_lock:
                cache["standings_rows"] = standings_rows
                cache["fixtures"] = fixtures_records
                cache["first_upcoming"] = first_upcoming
                cache["last_updated"] = time.time()
        except Exception as e:
            print(f"Worker error: {e}", flush = True)

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
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"},
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"},
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"},
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}
]}, {"name": "Round of 16", "matches": [
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"},
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}
]}, {"name": "Quarterfinals", "matches": [
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}
]}, {"name": "Semifinals", "matches": [
    {"team1": "home", "team2": "away"}, {"team1": "home", "team2": "away"}
]}, {"name": "Finals", "matches": [
    {"team1": "home", "team2": "away"}
]}]
app.layout = html.Div([
    html.H1("World Cup Tracker", style={"fontFamily": "sans-serif"}),
    html.P("My website for following the World Cup, inspired in part by Google's World Cup widget.", style={"fontFamily": "sans-serif"}),
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
        dcc.Tab(label="Fixtures", value="tab-1", style={"fontFamily": "sans-serif"}, children=[
            html.H2("Fixtures", style={"fontFamily": "sans-serif"}),
            dag.AgGrid(id="fixtures-grid", rowData=[], columnDefs=column_defs_fixtures, defaultColDef = default_col_def_fixtures, getRowId="params.data.id"),
        ]),
        dcc.Tab(label="Standings", value="tab-2", style={"fontFamily": "sans-serif"}, children=[
            html.H2("Standings", style={"fontFamily": "sans-serif"}),
            html.Div(
                [
                    html.Div([
                        html.H3("Group A", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-a", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group B", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-b", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group C", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-c", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group D", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-d", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group E", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-e", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group F", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-f", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group G", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-g", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group H", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-h", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group I", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-i", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group J", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-j", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group K", style={"fontFamily": "sans-serif"}),
                        dag.AgGrid(id="group-k", rowData=[], columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style, getRowId="params.data.id"),
                    ]),
                    html.Div([
                        html.H3("Group L", style={"fontFamily": "sans-serif"}),
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
        dcc.Tab(label="Bracket", value="tab-3", style={"fontFamily": "sans-serif"}, children=[
            html.H2("Bracket", style={"fontFamily": "sans-serif"}),
            html.Div(className="bracket", children=[
                html.Div(className="round", children=[
                    html.Div(className="match", children=[
                        html.Div(m["team1"]), html.Div(m["team2"])
                    ]) for m in round["matches"]
                ]) for round in ROUNDS
            ])
        ]),
    ]),
    html.Small(children = "", id="last-updated-display", style={"color": "gray", "fontFamily": "sans-serif"})
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
            return no_update, no_update, waiting_text, no_update
        
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

        return fixtures_update, updates(a, standings_rows[0]), updates(b, standings_rows[1]), updates(c, standings_rows[2]), updates(d, standings_rows[3]), updates(e, standings_rows[4]), updates(f, standings_rows[5]), updates(g, standings_rows[6]), updates(h, standings_rows[7]), updates(i, standings_rows[8]), updates(j, standings_rows[9]), updates(k, standings_rows[10]), updates(l, standings_rows[11]), last_updated, fixtures, standings_rows[0], standings_rows[1], standings_rows[2], standings_rows[3], standings_rows[4], standings_rows[5], standings_rows[6], standings_rows[7], standings_rows[8], standings_rows[9], standings_rows[10], standings_rows[11]
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
    
