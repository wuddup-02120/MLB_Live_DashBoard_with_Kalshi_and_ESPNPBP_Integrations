import requests
import json
from datetime import datetime, timedelta, timezone
from config import KALSHI_API_KEY, KALSHI_PRIVATE_KEY_PATH, POSTGRES_HOST, POSTGRES_DB, POSTGRES_PASSWORD, POSTGRES_PORT, POSTGRES_USER

import asyncio
import base64
import time
import websockets

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

import psycopg

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
            "market_ticker_team_2": team_2_market_ticker,
            "game_start_time": game_start_time
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

async def connect_to_kalshi(private_key, market_tickers, connection, batch_size=50):
    websocket_url = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"

    headers = create_websocket_headers(private_key)

    ticker_buffer = []
    last_flush_time = time.time()
    flush_interval = 10

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

        counter = 1

        try:

            while True:
                message = await websocket.recv()

                message_data = json.loads(message)

                ticker_record = parse_ticker_message(message_data)

                if ticker_record is not None:
                    ticker_buffer.append(ticker_record)

                buffer_full = len(ticker_buffer) >= batch_size
                time_to_flush = time.time() - last_flush_time >= flush_interval

                if ticker_buffer and (buffer_full or time_to_flush):
                    insert_ticker_records(
                        connection,
                        ticker_buffer
                    )

                    print(f'Inserted {len(ticker_buffer)} ticker records')
                    
                    ticker_buffer.clear()
                    last_flush_time = time.time()
        finally:
            if ticker_buffer:
                insert_ticker_records(
                    connection,
                    ticker_buffer
                )

def parse_ticker_message(message_data):

    if message_data.get("type") != "ticker":
        return None

    ticker_data = message_data['msg']

    ticker_record = {
        "market_id": ticker_data["market_id"],
        "market_ticker": ticker_data["market_ticker"],
        "price_dollars": ticker_data["price_dollars"],
        "yes_bid_dollars": ticker_data["yes_bid_dollars"],
        "yes_ask_dollars": ticker_data["yes_ask_dollars"],
        "volume_fp": ticker_data["volume_fp"],
        "open_interest_fp": ticker_data["open_interest_fp"],
        "yes_bid_size_fp": ticker_data["yes_bid_size_fp"],
        "yes_ask_size_fp": ticker_data["yes_ask_size_fp"],
        "last_trade_size_fp": ticker_data["last_trade_size_fp"],
        "ts_ms": ticker_data["ts_ms"],
        "time": ticker_data["time"]
    }

    return ticker_record

def connect_to_postgres():
    
    connection = psycopg.connect(
        host = POSTGRES_HOST,
        port = POSTGRES_PORT,
        dbname = POSTGRES_DB,
        user = POSTGRES_USER,
        password = POSTGRES_PASSWORD
    )

    return connection

def insert_ticker_records(connection, ticker_record):

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO kalshi_ticker_raw (
                market_id,
                market_ticker,
                price_dollars,
                yes_bid_dollars,
                yes_ask_dollars,
                volume_fp,
                open_interest_fp,
                yes_bid_size_fp,
                yes_ask_size_fp,
                last_trade_size_fp,
                ts_ms,
                event_time
            )
            VALUES (
                %(market_id)s,
                %(market_ticker)s,
                %(price_dollars)s,
                %(yes_bid_dollars)s,
                %(yes_ask_dollars)s,
                %(volume_fp)s,
                %(open_interest_fp)s,
                %(yes_bid_size_fp)s,
                %(yes_ask_size_fp)s,
                %(last_trade_size_fp)s,
                %(ts_ms)s,
                %(time)s
            );
            """,
            ticker_record
        )

    connection.commit()

def get_relevant_kalshi_mlb_events():

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

    return kalshi_mlb_events

def main():

    kalshi_mlb_events = get_relevant_kalshi_mlb_events()

    # Create empty market tickers array to be passed to the websocket connection
    # so kalshi knows which market ticker we want to subscribe to
    market_tickers = []

    for ticker, event_data in kalshi_mlb_events.items():
        team_1_market_ticker = event_data['market_ticker_team_1']
        team_2_market_ticker = event_data['market_ticker_team_2']
        market_tickers.append(team_1_market_ticker)
        market_tickers.append(team_2_market_ticker)

    private_key = load_private_key(KALSHI_PRIVATE_KEY_PATH)

    connection = connect_to_postgres()

    try:
        asyncio.run(
            connect_to_kalshi(
                private_key,
                market_tickers,
                connection
            )
        )
    finally:
        connection.close()

if __name__ == "__main__":
    main()
