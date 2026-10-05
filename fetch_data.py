import datetime
import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Optional, Sequence, Tuple, Union

import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_DB_PATH = Path(__file__).resolve().with_name("market_data_cache.sqlite3")
DateInput = Union[str, datetime.date, datetime.datetime, pd.Timestamp]
DateInterval = Tuple[datetime.date, datetime.date]


def _as_date(value: DateInput) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value

    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise ValueError("Date cannot be NaT.")
    return parsed.date()


@contextmanager
def _connect(database_path: Path) -> Generator[sqlite3.Connection, None, None]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    try:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS prices (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    adj_close REAL NOT NULL,
                    PRIMARY KEY (ticker, date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS coverage (
                    ticker TEXT PRIMARY KEY,
                    intervals_json TEXT NOT NULL
                )
                """
            )
            yield connection
    finally:
        connection.close()


def _read_coverage(connection: sqlite3.Connection, ticker: str) -> List[DateInterval]:
    row = connection.execute(
        "SELECT intervals_json FROM coverage WHERE ticker = ?", (ticker,)
    ).fetchone()
    if row is None:
        return []

    intervals = json.loads(row[0])
    if not isinstance(intervals, list):
        raise ValueError("Cached coverage must be a JSON list of date intervals.")

    parsed_intervals = []
    for interval in intervals:
        if (
            not isinstance(interval, list)
            or len(interval) != 2
            or not all(isinstance(boundary, str) for boundary in interval)
        ):
            raise ValueError("Cached coverage contains an invalid date interval.")
        start, end = (datetime.date.fromisoformat(boundary) for boundary in interval)
        if start > end:
            raise ValueError("Cached coverage contains a reversed date interval.")
        parsed_intervals.append((start, end))
    return parsed_intervals


def _is_covered(
    intervals: Sequence[DateInterval], requested_start: datetime.date, requested_end: datetime.date
) -> bool:
    return any(
        start <= requested_start and end >= requested_end for start, end in intervals
    )


def _merge_intervals(intervals: Sequence[DateInterval]) -> List[DateInterval]:
    merged: List[DateInterval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + datetime.timedelta(days=1):
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _extract_close_prices(
    downloaded: pd.DataFrame, tickers: Sequence[str]
) -> pd.DataFrame:
    if downloaded.empty and "Close" not in downloaded.columns:
        return pd.DataFrame()
    try:
        close_prices = downloaded["Close"]
    except KeyError as exc:
        raise ValueError("yfinance response did not contain closing prices.") from exc

    if isinstance(close_prices, pd.Series):
        close_prices = close_prices.to_frame(name=tickers[0])

    if isinstance(close_prices.columns, pd.MultiIndex):
        close_prices.columns = [
            next(
                (
                    str(part).strip().upper()
                    for part in column
                    if str(part).strip().upper() in tickers
                ),
                str(column[-1]).strip().upper(),
            )
            for column in close_prices.columns
        ]
    else:
        close_prices.columns = [
            str(column).strip().upper() for column in close_prices.columns
        ]
    return close_prices


def _load_cached_prices(
    connection: sqlite3.Connection,
    tickers: Sequence[str],
    start_date: datetime.date,
    end_date: datetime.date,
) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        rows.extend(
            (date, ticker, adj_close)
            for date, adj_close in connection.execute(
                """
                SELECT date, adj_close FROM prices
                WHERE ticker = ? AND date BETWEEN ? AND ?
                ORDER BY date
                """,
                (ticker, start_date.isoformat(), end_date.isoformat()),
            )
        )

    if not rows:
        return pd.DataFrame()

    price_rows = pd.DataFrame(rows, columns=["date", "ticker", "adj_close"])
    price_rows["date"] = pd.to_datetime(price_rows["date"])
    return (
        price_rows.pivot(index="date", columns="ticker", values="adj_close")
        .sort_index()
        .rename_axis(columns=None)
    )


def _store_fetched_prices(
    database_path: Path,
    close_prices: pd.DataFrame,
    tickers: Sequence[str],
    start_date: datetime.date,
    end_date: datetime.date,
) -> None:
    available_tickers = set(close_prices.columns)
    price_rows = []
    for ticker in tickers:
        if ticker not in available_tickers:
            logger.warning("yfinance returned no price series for %s.", ticker)
            continue
        for timestamp, value in close_prices[ticker].items():
            if pd.isna(value):
                continue
            price_date = _as_date(str(timestamp))
            price_rows.append(
                (ticker, price_date.isoformat(), float(value))
            )

    with _connect(database_path) as connection:
        if price_rows:
            connection.executemany(
                """
                INSERT OR REPLACE INTO prices (ticker, date, adj_close)
                VALUES (?, ?, ?)
                """,
                price_rows,
            )

        for ticker in tickers:
            if ticker not in available_tickers:
                continue
            intervals = _read_coverage(connection, ticker)
            intervals = _merge_intervals(
                intervals + [(start_date, end_date)]
            )
            serialized_intervals = [
                [start.isoformat(), end.isoformat()] for start, end in intervals
            ]
            connection.execute(
                """
                INSERT OR REPLACE INTO coverage (ticker, intervals_json)
                VALUES (?, ?)
                """,
                (ticker, json.dumps(serialized_intervals)),
            )


def fetch_historical_prices(
    tickers: List[str],
    start_date: DateInput,
    end_date: DateInput,
    *,
    cache_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    normalized_tickers = list(
        dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip())
    )
    if not normalized_tickers:
        return pd.DataFrame()

    requested_start = _as_date(start_date)
    requested_end = _as_date(end_date)
    if requested_start > requested_end:
        raise ValueError("Start date must be on or before end date.")

    database_path = Path(cache_path) if cache_path is not None else CACHE_DB_PATH
    with _connect(database_path) as connection:
        uncovered_tickers = [
            ticker
            for ticker in normalized_tickers
            if not _is_covered(
                _read_coverage(connection, ticker), requested_start, requested_end
            )
        ]

    if uncovered_tickers:
        try:
            downloaded = yf.download(
                uncovered_tickers,
                start=requested_start,
                end=requested_end + datetime.timedelta(days=1),
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception:
            logger.exception("Failed to fetch data from yfinance.")
            raise
        if downloaded is None:
            raise RuntimeError("yfinance returned no response.")
        close_prices = _extract_close_prices(downloaded, uncovered_tickers)
        _store_fetched_prices(
            database_path,
            close_prices,
            uncovered_tickers,
            requested_start,
            requested_end,
        )

    with _connect(database_path) as connection:
        cached_prices = _load_cached_prices(
            connection, normalized_tickers, requested_start, requested_end
        )
    return clean_price_data(cached_prices)


def clean_price_data(prices_df: pd.DataFrame) -> pd.DataFrame:
    if prices_df.empty:
        return prices_df

    cleaned_df = prices_df.ffill()
    return cleaned_df.dropna(how="all")
