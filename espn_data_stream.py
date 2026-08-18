import requests
import json
from datetime import datetime, timedelta, timezone
import re

import asyncio

def get_team_mapping():
    with open("team_mapping.json", "r") as file:
        return json.load(file)

def get_mlb_game_events():

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=3)
    window_end = now + timedelta(hours=3)

    mlb_games_espn_url = "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/events"

    response = requests.get(mlb_games_espn_url)
    data = response.json()

    espn_game_ids = {}

    for item in data['items']:
        game_url = item['$ref']
        game_response = requests.get(game_url)
        game_data = game_response.json()

        game_id = game_data['id']
        game_name = game_data['name']
        game_date = game_data['date']

        game_start_time = datetime.fromisoformat(game_date.replace('Z', '+00:00'))

        if window_start <= game_start_time <= window_end:
            espn_game_ids[game_id] = {
                "game_name": game_name,
                "game_start_time": game_start_time
            }

    return espn_game_ids

def match_kalshi_games_to_espn(kalshi_games):

    team_mapping = get_team_mapping()
    espn_games = get_mlb_game_events()

    matched_games = {}

    for kalshi_event_ticker, kalshi_game in kalshi_games.items():

        team_1_kalshi, team_2_kalshi = kalshi_game["matchup"].split(
            " vs ",
            maxsplit=1
        )

        team_2_kalshi = team_2_kalshi.split(": Game")[0]

        team_1_espn = team_mapping[team_1_kalshi]
        team_2_espn = team_mapping[team_2_kalshi]

        kalshi_matchup_key = frozenset([
            team_1_espn,
            team_2_espn
        ])

        kalshi_start_time = kalshi_game["game_start_time"]

        possible_matches = []

        for espn_game_id, espn_game in espn_games.items():

            game_name = espn_game["game_name"]
            espn_start_time = espn_game["game_start_time"]

            espn_team_1, espn_team_2 = re.split(
                r" vs | at ",
                game_name,
                maxsplit=1
            )

            espn_matchup_key = frozenset([
                espn_team_1,
                espn_team_2
            ])

            if espn_matchup_key == kalshi_matchup_key:
                time_difference = abs(
                    espn_start_time - kalshi_start_time
                )

                possible_matches.append({
                    "espn_game_id": espn_game_id,
                    "time_difference": time_difference
                })

        if possible_matches:

            best_match = min(
                possible_matches,
                key=lambda match: match["time_difference"]
            )

            if best_match["time_difference"] <= timedelta(minutes=30):
                matched_games[kalshi_event_ticker] = {
                    "kalshi_event_ticker": kalshi_event_ticker,
                    "espn_game_id": best_match["espn_game_id"]
                }

    return matched_games

def parse_espn_plays(
    plays,
    espn_game_id,
    kalshi_event_ticker
):

    play_records = []

    for play in plays:

        play_record = {
            "espn_play_id": play.get("id"),
            "espn_game_id": espn_game_id,
            "kalshi_event_ticker": kalshi_event_ticker,

            "sequence_number": play.get("sequenceNumber"),
            "play_text": play.get("text"),
            "play_type": play.get("type", {}).get("text"),

            "inning": play.get("period", {}).get("number"),
            "inning_half": play.get("period", {}).get("type"),

            "away_score": play.get("awayScore"),
            "home_score": play.get("homeScore"),
            "scoring_play": play.get("scoringPlay"),
            "score_value": play.get("scoreValue"),
            "outs": play.get("outs"),

            "at_bat_id": play.get("atBatId"),
            "at_bat_pitch_number": play.get("atBatPitchNumber"),

            "balls": play.get("pitchCount", {}).get("balls"),
            "strikes": play.get("pitchCount", {}).get("strikes"),

            "pitch_velocity": play.get("pitchVelocity"),
            "pitch_type": play.get("pitchType", {}).get("text"),
            "pitch_type_abbreviation": play.get(
                "pitchType", {}
            ).get("abbreviation"),

            "pitch_coordinate_x": play.get(
                "pitchCoordinate", {}
            ).get("x"),

            "pitch_coordinate_y": play.get(
                "pitchCoordinate", {}
            ).get("y"),

            "on_first_athlete_id": play.get(
                "onFirst", {}
            ).get("athlete", {}).get("id"),

            "on_second_athlete_id": play.get(
                "onSecond", {}
            ).get("athlete", {}).get("id"),

            "on_third_athlete_id": play.get(
                "onThird", {}
            ).get("athlete", {}).get("id"),

            "event_time": play.get("wallclock")
        }

        play_records.append(play_record)

    return play_records

def insert_espn_play_records(connection, play_records):

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO espn_play_raw (
                espn_play_id,
                espn_game_id,
                kalshi_event_ticker,
                sequence_number,
                play_text,
                play_type,
                inning,
                inning_half,
                away_score,
                home_score,
                scoring_play,
                score_value,
                outs,
                at_bat_id,
                at_bat_pitch_number,
                balls,
                strikes,
                pitch_velocity,
                pitch_type,
                pitch_type_abbreviation,
                pitch_coordinate_x,
                pitch_coordinate_y,
                on_first_athlete_id,
                on_second_athlete_id,
                on_third_athlete_id,
                event_time
            )
            VALUES (
                %(espn_play_id)s,
                %(espn_game_id)s,
                %(kalshi_event_ticker)s,
                %(sequence_number)s,
                %(play_text)s,
                %(play_type)s,
                %(inning)s,
                %(inning_half)s,
                %(away_score)s,
                %(home_score)s,
                %(scoring_play)s,
                %(score_value)s,
                %(outs)s,
                %(at_bat_id)s,
                %(at_bat_pitch_number)s,
                %(balls)s,
                %(strikes)s,
                %(pitch_velocity)s,
                %(pitch_type)s,
                %(pitch_type_abbreviation)s,
                %(pitch_coordinate_x)s,
                %(pitch_coordinate_y)s,
                %(on_first_athlete_id)s,
                %(on_second_athlete_id)s,
                %(on_third_athlete_id)s,
                %(event_time)s
            )
            ON CONFLICT (espn_play_id) DO NOTHING;
            """,
            play_records
        )

        inserted_count = cursor.rowcount

    connection.commit()

    return inserted_count

def pull_single_game_play_by_play(
    kalshi_event_ticker,
    espn_game_id
):

    espn_play_by_play_url_base = (
        "https://site.web.api.espn.com/apis/site/v2/"
        "sports/baseball/mlb/summary"
    )

    params_espn_play_by_play = {
        "region": "us",
        "lang": "en",
        "contentorigin": "espn",
        "event": espn_game_id
    }

    response = requests.get(
        espn_play_by_play_url_base,
        params=params_espn_play_by_play,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    plays = data.get("plays", [])

    play_records = parse_espn_plays(
        plays,
        espn_game_id,
        kalshi_event_ticker
    )

    return play_records

async def poll_single_espn_game(
    kalshi_event_ticker,
    espn_game_id,
    connection,
    poll_interval=3
):

    while True:

        try:
            play_records = await asyncio.to_thread(
                pull_single_game_play_by_play,
                kalshi_event_ticker,
                espn_game_id
            )

            if play_records:

                inserted_count = await asyncio.to_thread(
                    insert_espn_play_records,
                    connection,
                    play_records
                )

                print(
                    f"ESPN game {espn_game_id}: "
                    f"{inserted_count} new plays inserted "
                    f"({len(play_records)} returned)"
                )

        except Exception as error:

            connection.rollback()

            print(
                f"Error polling ESPN game {espn_game_id}: "
                f"{error}"
            )

        await asyncio.sleep(poll_interval)

def main():
    espn_games = get_mlb_game_events()
    print(espn_games)

if __name__ == "__main__":
    main()

