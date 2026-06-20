import threading
import time
from dash import Dash, html, clientside_callback, Input, Output, State, dcc, dash
import dash_ag_grid as dag
import requests
import string
import pandas as pd
import datetime
from dotenv import load_dotenv
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
    {'field': 'time', 'headerName': 'Time', "width": 80},
    {'field': 'city', 'headerName': 'Location'},
    {'field': 'round', 'headerName': 'Round'},
    {'field': 'status', 'headerName': 'Status', "width": 150, "enableCellChangeFlash": True},
    {'field': 'home', 'headerName': '', "cellRenderer": "HomeRenderer", "enableCellChangeFlash": True},
    {'field': 'score', 'headerName': '', "width": 100, "enableCellChangeFlash": True},
    {'field': 'away', 'headerName': '', "cellRenderer": "AwayRenderer", "enableCellChangeFlash": True},
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
            fixtures['date'] = fixtures['timestamp'].apply(lambda x: datetime.datetime.fromtimestamp(x).strftime('%Y-%m-%d'))
            fixtures['time'] = fixtures['timestamp'].apply(lambda x: datetime.datetime.fromtimestamp(x).strftime('%H:%M'))
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

app.layout = html.Div([
    dcc.Interval(id="scroll-trigger", interval=300, max_intervals=1),
    html.Div(id="scroll-dummy", style={"display": "none"}),
    dcc.Store(id="scroll-target-store"),
    dcc.Store(id="fixtures-rows"),
    dcc.Interval(id="tick", interval=5_000),  # adjust interval as needed
    html.H2("Fixtures", style={"fontFamily": "sans-serif"}),
    dag.AgGrid(id="fixtures-grid", rowData=[], columnDefs=column_defs_fixtures, defaultColDef = default_col_def_fixtures, getRowId="params.data.id"),
    html.H2("Standings", style={"fontFamily": "sans-serif"}),
    html.Div(
        children = [], 
        style = {
            "display": "grid",
            "gridTemplateColumns": "repeat(2, 1fr)",
            "gap": "32px",
        }, 
        id="standings-grid"
    ),
    html.Small(children = "", id="last-updated-display", style={"color": "gray", "fontFamily": "sans-serif"})
], id = 'whole-thing')

@app.callback(
    Output("fixtures-grid", "rowTransaction"),           # ← match your grid's id
    Output("standings-grid", "children"),    # ← one Output per grid
    Output("last-updated-display", "children"),
    Output("fixtures-rows", "data"),
    Input("tick", "n_intervals"),
    State("fixtures-rows", "data"),
)
def refresh_grids(n, previous_rows):
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

        standings_grids = [
            html.Div([
                html.H3(f"Group {string.ascii_uppercase[idx]}", style={"fontFamily": "sans-serif"}),
                dag.AgGrid(rowData=row_data, columnDefs=column_defs, defaultColDef = default_col_def, getRowStyle = get_row_style, dashGridOptions = dash_grid_options, style = style),
            ]) for idx, row_data in enumerate(standings_rows)
        ]
        last_updated = f"Last updated: {time.strftime('%H:%M:%S', time.localtime(ts))}"
        
        previous_dict = {r["id"]: r for r in (previous_rows or [])}
        to_add, to_update = [], []
        for row in fixtures:
            if row["id"] not in previous_dict:
                to_add.append(row)
            elif previous_dict[row["id"]] != row:
                to_update.append(row)
                print('diagnostics:', row, flush = True)
                print('diagnostics:', previous_dict[row["id"]], flush = True)
        
        
        print('diagnostics:', len(to_add), len(to_update), flush = True)
        return {"add": to_add, "update": to_update}, standings_grids, last_updated, fixtures
    except Exception as e:
        import traceback
        print(traceback.format_exc())   # shows in server logs
        raise

if __name__ == "__main__":
    app.run(debug=True)
    
