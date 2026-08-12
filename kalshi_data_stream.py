import requests
import json
from datetime import datetime, timedelta, timezone
from config import KALSHI_API_KEY, KALSHI_PRIVATE_KEY_PATH

import asyncio
import base64
import time
import websockets

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

def get_kalshi_mlb_event_core_info():

    url = "https://external-api.kalshi.com/trade-api/v2/events"

    event_tickers = {}
    cursor = None

    while True:
        params = {
            "limit": 200,
            "status": "open",
            "with_nested_markets": True,
            "series_ticker": "KXMLBGAME"
        }

        if cursor is not None:
            params['cursor'] = cursor

        response = requests.get(url, params=params)
        response.raise_for_status()

        kalshi_mlb_events = response.json()

        for event in kalshi_mlb_events['events']:
            event_ticker = event['event_ticker']
            event_title = event['title']
            event_sub_title = event['sub_title']
            event_tickers[event_ticker] = {
                "event_title": event_title,
                "event_sub": event_sub_title
            }
        cursor = kalshi_mlb_events['cursor']

        if not cursor:
            break

    return event_tickers

def parse_teams(event_sub_title):

    matchup_only = event_sub_title.split(" (", maxsplit=1)[0]
    team_1, team_2 = matchup_only.split(" vs ", maxsplit=1)

    return team_1, team_2
     
def get_kalshi_mlb_event_data(window_start, window_end, ticker, event_sub, event_title):

    event_url = (
        f"https://external-api.kalshi.com/"
        f"trade-api/v2/events/{ticker}"
    )

    event_response = requests.get(event_url)
    event_response.raise_for_status()

    event_data = event_response.json()
    market = event_data['markets'][0]

    market_date = market['occurrence_datetime']
    market_date_formatted = datetime.fromisoformat(market_date.replace("Z", "+00:00"))
    game_start_time = market_date_formatted - timedelta(hours=3)

    team_1, team_2 = parse_teams(event_sub)

    team_1_market_ticker = create_market_ticker_for_event(ticker, team_1)
    team_2_market_ticker = create_market_ticker_for_event(ticker, team_2)

    if window_start <= game_start_time <= window_end:
        event_entry = {
            "matchup": event_title,
            "matchup_team_1": team_1,
            "matchup_team_2": team_2,
            "market_ticker_team_1": team_1_market_ticker,
            "market_ticker_team_2": team_2_market_ticker
        }

        return event_entry

    return None

def create_market_ticker_for_event(ticker, team):
    return f"{ticker}-{team}"

def load_private_key(file_path):
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(key_file.read(), password=None)
    return private_key

def sign_message(private_key, text):
    message = text.encode('utf-8')

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )

    return base64.b64encode(signature).decode('utf-8')

def create_websocket_headers(private_key):
    timestamp = str(int(time.time() * 1000))

    message = (
        timestamp
        + "GET"
        + "/trade-api/ws/v2"
    )

    signature = sign_message(
        private_key,
        message
    )

    headers = {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp
    }

    return headers

async def connect_to_kalshi(private_key, market_tickers):
    websocket_url = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"

    headers = create_websocket_headers(private_key)

    async with websockets.connect(
        websocket_url,
        additional_headers=headers
    ) as websocket:
        print('Connected to Kalshi Websocket')

        subscription_message = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ['ticker'],
                "market_tickers": market_tickers
            }
        }

        await websocket.send(
            json.dumps(subscription_message)
        )

        print(f'Subscribed to {market_tickers}')

        while True:
            message = await websocket.recv()
            print(message)

def main():
    # Define static time-related variables
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=3)
    window_end = now + timedelta(hours=3)

    # Create dict populated with information needed to make specific event requests and build events dict
    event_tickers = get_kalshi_mlb_event_core_info()

    # Create empty mlb event dict and populate it with relevant events and information needed to construct market ticker(s)
    kalshi_mlb_events = {}

    for event_ticker, event_data in event_tickers.items():
        event_sub = event_data['event_sub']
        event_title = event_data['event_title']
        event_entry = get_kalshi_mlb_event_data(window_start, window_end, event_ticker, event_sub, event_title)
        if event_entry is not None:
            kalshi_mlb_events[event_ticker] = event_entry

    # Create empty market tickers array to be passed to the websocket connection
    # so kalshi knows which market ticker we want to subscribe to
    market_tickers = []

    for ticker, event_data in kalshi_mlb_events.items():
        team_1_market_ticker = event_data['market_ticker_team_1']
        team_2_market_ticker = event_data['market_ticker_team_2']
        market_tickers.append(team_1_market_ticker)
        market_tickers.append(team_2_market_ticker)

    private_key = load_private_key(KALSHI_PRIVATE_KEY_PATH)

    asyncio.run(connect_to_kalshi(private_key, market_tickers))

if __name__ == "__main__":
    main()
