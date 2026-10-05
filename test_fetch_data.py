import datetime
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import fetch_data


def _download_response(tickers, dates, values):
    response = pd.DataFrame(
        {ticker: values[ticker] for ticker in tickers},
        index=pd.to_datetime(dates),
    )
    response.columns = pd.MultiIndex.from_product([["Close"], tickers])
    return response


class FetchHistoricalPricesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "cache.sqlite3"
        self.start = datetime.date(2024, 1, 2)
        self.end = datetime.date(2024, 1, 3)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_batches_uncovered_tickers_and_skips_fully_covered_request(self):
        response = _download_response(
            ["AAA", "BBB"],
            ["2024-01-02", "2024-01-03"],
            {"AAA": [10.0, 11.0], "BBB": [20.0, 21.0]},
        )
        with patch("fetch_data.yf.download", return_value=response) as download:
            prices = fetch_data.fetch_historical_prices(
                ["aaa", "BBB"], self.start, self.end, cache_path=self.database_path
            )
            self.assertEqual(download.call_count, 1)
            self.assertEqual(download.call_args.args[0], ["AAA", "BBB"])
            self.assertEqual(download.call_args.kwargs["end"], datetime.date(2024, 1, 4))

            cached_prices = fetch_data.fetch_historical_prices(
                ["AAA", "BBB"], self.start, self.end, cache_path=self.database_path
            )
            self.assertEqual(download.call_count, 1)

        pd.testing.assert_frame_equal(prices, cached_prices)
        self.assertEqual(list(prices.columns), ["AAA", "BBB"])
        self.assertEqual(prices.loc[pd.Timestamp("2024-01-03"), "BBB"], 21.0)

    def test_existing_coverage_fetches_only_uncovered_tickers(self):
        with sqlite3.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE prices (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    adj_close REAL NOT NULL,
                    PRIMARY KEY (ticker, date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE coverage (
                    ticker TEXT PRIMARY KEY,
                    intervals_json TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                "INSERT INTO prices (ticker, date, adj_close) VALUES (?, ?, ?)",
                [
                    ("AAA", "2024-01-02", 100.0),
                    ("AAA", "2024-01-03", 101.0),
                ],
            )
            connection.execute(
                "INSERT INTO coverage (ticker, intervals_json) VALUES (?, ?)",
                ("AAA", json.dumps([["2024-01-01", "2024-01-04"]])),
            )

        response = _download_response(
            ["BBB"],
            ["2024-01-02", "2024-01-03"],
            {"BBB": [20.0, 21.0]},
        )
        with patch("fetch_data.yf.download", return_value=response) as download:
            prices = fetch_data.fetch_historical_prices(
                ["AAA", "BBB"], self.start, self.end, cache_path=self.database_path
            )

        self.assertEqual(download.call_count, 1)
        self.assertEqual(download.call_args.args[0], ["BBB"])
        self.assertEqual(download.call_args.kwargs["start"], self.start)
        self.assertEqual(download.call_args.kwargs["end"], datetime.date(2024, 1, 4))
        self.assertEqual(list(prices.columns), ["AAA", "BBB"])
        self.assertEqual(prices.loc[pd.Timestamp("2024-01-02"), "AAA"], 100.0)
        self.assertEqual(prices.loc[pd.Timestamp("2024-01-03"), "AAA"], 101.0)
        self.assertEqual(prices.loc[pd.Timestamp("2024-01-02"), "BBB"], 20.0)
        self.assertEqual(prices.loc[pd.Timestamp("2024-01-03"), "BBB"], 21.0)

    def test_partial_coverage_fetches_full_requested_range_and_merges_intervals(self):
        with patch(
            "fetch_data.yf.download",
            return_value=_download_response(
                ["AAA"], ["2024-01-02"], {"AAA": [10.0]}
            ),
        ) as first_download:
            fetch_data.fetch_historical_prices(
                ["AAA"],
                datetime.date(2024, 1, 2),
                datetime.date(2024, 1, 2),
                cache_path=self.database_path,
            )
            self.assertEqual(first_download.call_count, 1)

        with patch(
            "fetch_data.yf.download",
            return_value=_download_response(
                ["AAA"], ["2024-01-02", "2024-01-03"], {"AAA": [12.0, 13.0]}
            ),
        ) as second_download:
            prices = fetch_data.fetch_historical_prices(
                ["AAA"],
                datetime.date(2024, 1, 2),
                datetime.date(2024, 1, 3),
                cache_path=self.database_path,
            )
            self.assertEqual(second_download.call_count, 1)
            self.assertEqual(second_download.call_args.kwargs["start"], self.start)
            self.assertEqual(second_download.call_args.kwargs["end"], datetime.date(2024, 1, 4))

        with sqlite3.connect(str(self.database_path)) as connection:
            coverage = connection.execute(
                "SELECT intervals_json FROM coverage WHERE ticker = 'AAA'"
            ).fetchone()[0]
        self.assertEqual(
            json.loads(coverage), [["2024-01-02", "2024-01-03"]]
        )
        self.assertEqual(prices.loc[pd.Timestamp("2024-01-02"), "AAA"], 12.0)

    def test_failed_yfinance_call_does_not_record_coverage(self):
        with patch(
            "fetch_data.yf.download", side_effect=RuntimeError("network unavailable")
        ) as download:
            with self.assertRaisesRegex(RuntimeError, "network unavailable"):
                fetch_data.fetch_historical_prices(
                    ["AAA"], self.start, self.end, cache_path=self.database_path
                )
            self.assertEqual(download.call_count, 1)

        with sqlite3.connect(str(self.database_path)) as connection:
            coverage_count = connection.execute(
                "SELECT COUNT(*) FROM coverage"
            ).fetchone()[0]
            price_count = connection.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        self.assertEqual(coverage_count, 0)
        self.assertEqual(price_count, 0)

    def test_partial_response_only_caches_returned_tickers(self):
        with patch(
            "fetch_data.yf.download",
            return_value=_download_response(
                ["AAA"], ["2024-01-02"], {"AAA": [10.0]}
            ),
        ) as first_download:
            fetch_data.fetch_historical_prices(
                ["AAA", "BBB"], self.start, self.start, cache_path=self.database_path
            )
            self.assertEqual(first_download.call_count, 1)

        with sqlite3.connect(str(self.database_path)) as connection:
            cached_tickers = connection.execute(
                "SELECT ticker FROM coverage ORDER BY ticker"
            ).fetchall()
        self.assertEqual(cached_tickers, [("AAA",)])

        with patch(
            "fetch_data.yf.download",
            return_value=_download_response(
                ["BBB"], ["2024-01-02"], {"BBB": [20.0]}
            ),
        ) as second_download:
            fetch_data.fetch_historical_prices(
                ["AAA", "BBB"], self.start, self.start, cache_path=self.database_path
            )
            self.assertEqual(second_download.call_count, 1)
            self.assertEqual(second_download.call_args.args[0], ["BBB"])


if __name__ == "__main__":
    unittest.main()
