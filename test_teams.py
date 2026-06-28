from dotenv import load_dotenv
import requests
import os
import pandas as pd

load_dotenv()  # only does something if .env exists locally; harmless if not
api_key = os.environ.get("API_KEY")

headers = {'x-apisports-key': api_key}
payload = {'league': 1, 'season': 2026}

response_teams = requests.get(url = 'https://v3.football.api-sports.io/teams', headers = headers, params = payload)
response_teams = response_teams.json().get('response')
response_teams =  pd.json_normalize(response_teams)
team_ids = response_teams.set_index('team.id')
print(response_teams.head())