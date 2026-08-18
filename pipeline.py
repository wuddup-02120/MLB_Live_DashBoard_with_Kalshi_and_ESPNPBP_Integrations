import asyncio

from config import KALSHI_PRIVATE_KEY_PATH

from kalshi_data_stream import (
    get_relevant_kalshi_mlb_events,
    connect_to_postgres,
    load_private_key,
    connect_to_kalshi
)

from espn_data_stream import (
    match_kalshi_games_to_espn,
    poll_single_espn_game
)


async def run_pipeline():

    kalshi_games = get_relevant_kalshi_mlb_events()

    matched_games = match_kalshi_games_to_espn(
        kalshi_games
    )

    market_tickers = []

    for event_data in kalshi_games.values():
        market_tickers.append(
            event_data["market_ticker_team_1"]
        )

        market_tickers.append(
            event_data["market_ticker_team_2"]
        )

    private_key = load_private_key(
        KALSHI_PRIVATE_KEY_PATH
    )

    kalshi_connection = connect_to_postgres()
    espn_connections = []

    espn_tasks = []

    try:

        for kalshi_event_ticker, access_info in matched_games.items():

            espn_game_id = access_info["espn_game_id"]

            espn_connection = connect_to_postgres()

            espn_connections.append(
                espn_connection
            )

            espn_tasks.append(
                poll_single_espn_game(
                    kalshi_event_ticker,
                    espn_game_id,
                    espn_connection
                )
            )

        await asyncio.gather(
            connect_to_kalshi(
                private_key,
                market_tickers,
                kalshi_connection
            ),
            *espn_tasks
        )

    finally:

        kalshi_connection.close()

        for connection in espn_connections:
            connection.close()

        print("Database connections closed")


def main():

    try:
        asyncio.run(
            run_pipeline()
        )

    except KeyboardInterrupt:
        print("\nPipeline stopped by user")

if __name__ == "__main__":
    main()