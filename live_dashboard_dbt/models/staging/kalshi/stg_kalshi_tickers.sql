select
    id as ticker_record_id,
    market_id,
    market_ticker,

    price_dollars::numeric as last_price,
    yes_bid_dollars::numeric as yes_bid,
    yes_ask_dollars::numeric as yes_ask,

    volume_fp::numeric as volume,
    open_interest_fp::numeric as open_interest,

    yes_bid_size_fp::numeric as yes_bid_size,
    yes_ask_size_fp::numeric as yes_ask_size,
    last_trade_size_fp::numeric as last_trade_size,

    ts_ms as kalshi_timestamp_ms,
    event_time as kalshi_event_time,
    ingested_at

from {{ source('raw', 'kalshi_ticker_raw') }}