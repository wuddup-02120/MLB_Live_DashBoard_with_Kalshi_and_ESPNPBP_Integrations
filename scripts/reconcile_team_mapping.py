import json
import requests

def get_espn_team_names():

    url = "http://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/seasons/2026/teams?limit=50"

    response = requests.get(url)
    espn_teams = response.json()

    unique_teams = set()

    for team in espn_teams['items']:
        team_url = team['$ref']

        team_response = requests.get(team_url)
        team_info = team_response.json()

        unique_teams.add(team_info['displayName'])

    return unique_teams

def get_kalshi_team_names():

    url = "https://external-api.kalshi.com/trade-api/v2/events?limit=200&series_ticker=KXMLBGAME"

    response = requests.get(url)
    matchups = response.json()

    matchups_raw = []

    for event in matchups['events']:
        matchups_raw.append(event['title'])

    unique_teams = set()

    for matchup in matchups_raw:
        if "All-Star Game" in matchup:
            continue

        team1, team2 = matchup.split(" vs ")
        team2 = team2.split(": Game")[0]

        unique_teams.add(team1)
        unique_teams.add(team2)

    return unique_teams

def map_team_names(espn_teams, kalshi_teams):

    team_name_mapping = {}
    unique_teams_espn = list(espn_teams)
    unique_teams_kalshi = list(kalshi_teams)

    for kalshi_team in unique_teams_kalshi:

        possible_matches = []

        for espn_team in unique_teams_espn:
            if espn_team.startswith(kalshi_team):
                possible_matches.append(espn_team)

        if len(possible_matches) == 1:
            team_name_mapping[kalshi_team] = possible_matches[0]

    team_name_mapping["A's"] = 'Athletics'
    team_name_mapping["Chicago WS"] = 'Chicago White Sox'

    return team_name_mapping

def main():
    espn_unqiue_teams = get_espn_team_names()
    kalshi_unique_teams = get_kalshi_team_names()

    team_mapping = map_team_names(espn_unqiue_teams, kalshi_unique_teams)

    with open('team_mapping.json', 'w', encoding='utf-8') as file:
        json.dump(team_mapping, file, indent=4)

if __name__ == "__main__":
    main()