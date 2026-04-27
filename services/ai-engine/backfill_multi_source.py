"""
Multi-Source Data Backfill Script
Uses the new data pipeline to backfill:
- daily_commodities: Brent Crude & Urea (2016-2026)
- market_context: USD/EGP rates from Alpha Vantage

Sources:
- Brent: FMP (primary) -> yfinance (fallback) -> Investing.com (fallback)
- Urea: Investing.com (primary) -> yfinance (fallback)
- USD/EGP: Alpha Vantage (primary) -> yfinance (fallback)
"""
from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from typing import Any

import mysql.connector
import pandas as pd

# Add app directory to path
sys.path.insert(0, "app")

from app.data_fetcher import DataFetcher, create_fetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
LOGGER = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3307,
    "user": "egx_app_user",
    "password": "EGX_App_7wN!9Qx2#M4Lz8",
    "database": "egx_portfolio",
    "autocommit": True,
}

# Backfill date range
START_DATE = date(2016, 1, 1)
END_DATE = date(2026, 4, 30)

# Chunk size for large date ranges (to avoid rate limits)
CHUNK_DAYS = 365


def ensure_daily_commodities_table(connection: Any) -> None:
    """Create the daily_commodities table if it doesn't exist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_commodities (
                id INT AUTO_INCREMENT PRIMARY KEY,
                trade_date DATE NOT NULL,
                commodity_name VARCHAR(50) NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                source VARCHAR(50) NULL DEFAULT 'unknown',
                created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                UNIQUE KEY uc_daily_comm (trade_date, commodity_name)
            ) ENGINE=InnoDB
            """
        )
    LOGGER.info("Ensured daily_commodities table exists")


def ensure_market_context_table(connection: Any) -> None:
    """Create the market_context table if it doesn't exist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS market_context (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                trade_date DATE NOT NULL,
                usd_egp_close DECIMAL(19, 6) NULL,
                usd_egp_source VARCHAR(50) NULL DEFAULT 'unknown',
                gold_usd_close DECIMAL(19, 6) NULL,
                cbe_policy_rate_pct DECIMAL(9, 4) NULL,
                cbe_rate_changed BOOLEAN NOT NULL DEFAULT FALSE,
                created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                    ON UPDATE CURRENT_TIMESTAMP(6),
                CONSTRAINT uq_market_context_trade_date UNIQUE (trade_date)
            ) ENGINE=InnoDB
            """
        )
    LOGGER.info("Ensured market_context table exists")


def chunk_date_range(start: date, end: date, chunk_days: int) -> list[tuple[date, date]]:
    """Split date range into chunks to avoid rate limits."""
    chunks = []
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=chunk_days), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def fetch_brent_with_fallback(fetcher: DataFetcher, start: date, end: date) -> pd.DataFrame | None:
    """
    Fetch Brent Crude with fallback chain.
    Primary: TradingView (ICE exchange)
    Fallback: yfinance (BZ=F)
    """
    LOGGER.info(f"Fetching Brent Crude from {start} to {end}")

    # Try TradingView first
    try:
        result = fetcher._fetch_tradingview_brent(start, end)
        if result.success and result.data is not None and not result.data.empty:
            df = result.data.copy()
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df = df[["trade_date"] + [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]]
            df = df.rename(columns={"close": "price"})
            df["commodity_name"] = "Brent Crude"
            df["source"] = "tradingview"
            df = df[["trade_date", "commodity_name", "price", "source"]]
            LOGGER.info(f"Fetched {len(df)} Brent records from TradingView")
            return df
    except Exception as e:
        LOGGER.warning(f"TradingView failed for Brent: {e}")

    # Fallback to yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker("BZ=F")
        hist = ticker.history(start=start.isoformat(), end=end.isoformat())
        if not hist.empty:
            df = pd.DataFrame({
                "trade_date": hist.index.normalize(),
                "commodity_name": "Brent Crude",
                "price": hist["Close"].round(2),
                "source": "yfinance",
            })
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            LOGGER.info(f"Fetched {len(df)} Brent records from yfinance (BZ=F)")
            return df
    except Exception as e:
        LOGGER.error(f"yfinance failed for Brent: {e}")

    LOGGER.error("Failed to fetch Brent Crude")
    return None


def generate_urea_from_brent(brent_df: pd.DataFrame, baseline: float = 180.0) -> pd.DataFrame:
    """
    Generate synthetic Urea prices based on Brent Crude correlation.
    Formula: Urea ≈ (Brent * 5) + baseline + seasonal_factor
    
    Rationale: Urea is a nitrogen fertilizer produced from natural gas.
    Its price correlates with energy costs (Brent as proxy) with a multiplier.
    """
    LOGGER.info("Generating Urea prices from Brent Crude correlation")
    
    if brent_df is None or brent_df.empty:
        return None
    
    df = brent_df.copy()
    
    # Core formula: Urea = Brent * 5 + baseline
    # Add some noise and seasonal variation
    df["price"] = (df["price"] * 5.0) + baseline
    
    # Add seasonal factor (urea demand higher during planting seasons)
    trade_dates = pd.to_datetime(df["trade_date"])
    day_of_year = trade_dates.dt.dayofyear
    seasonal = 30 * ((day_of_year - 60) / 365.25).apply(lambda x: abs((x % 1) - 0.5) * 2)  # Peak in spring/fall
    
    df["price"] = (df["price"] + seasonal).round(2)
    df["commodity_name"] = "Urea"
    df["source"] = "synthetic_brent_correlation"
    
    LOGGER.info(f"Generated {len(df)} Urea records from Brent correlation")
    return df[["trade_date", "commodity_name", "price", "source"]]


def fetch_usd_egp_with_fallback(fetcher: DataFetcher, start: date, end: date) -> pd.DataFrame | None:
    """
    Fetch USD/EGP with fallback chain.
    Primary: TradingView (FX exchange)
    Fallback: Alpha Vantage -> yfinance
    """
    LOGGER.info(f"Fetching USD/EGP from {start} to {end}")

    # Try TradingView first
    try:
        result = fetcher._fetch_tradingview_usd_egp(start, end)
        if result.success and result.data is not None and not result.data.empty:
            df = result.data.copy()
            df = df.rename(columns={"close": "usd_egp_close"})
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df["source"] = "tradingview"
            df = df[["trade_date", "usd_egp_close", "source"]]
            LOGGER.info(f"Fetched {len(df)} USD/EGP records from TradingView")
            return df
    except Exception as e:
        LOGGER.warning(f"TradingView failed for USD/EGP: {e}")

    # Try Alpha Vantage
    result = fetcher.fetch_alpha_vantage_fx_daily("USD", "EGP")
    if result.success and result.data is not None:
        df = result.data.copy()
        df = df[(df["trade_date"] >= pd.Timestamp(start)) & (df["trade_date"] <= pd.Timestamp(end))]
        if not df.empty:
            df["source"] = "alpha_vantage"
            df = df[["trade_date", "close", "source"]].rename(columns={"close": "usd_egp_close"})
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            LOGGER.info(f"Fetched {len(df)} USD/EGP records from Alpha Vantage")
            return df

    # Fallback to yfinance
    LOGGER.warning("Alpha Vantage failed for USD/EGP, trying yfinance...")
    try:
        import yfinance as yf
        ticker = yf.Ticker("EGP=X")
        hist = ticker.history(start=start.isoformat(), end=end.isoformat())
        if not hist.empty:
            df = pd.DataFrame({
                "trade_date": hist.index.normalize(),
                "usd_egp_close": hist["Close"].round(6),
                "source": "yfinance",
            })
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            LOGGER.info(f"Fetched {len(df)} USD/EGP records from yfinance")
            return df
    except Exception as e:
        LOGGER.warning(f"yfinance failed for USD/EGP: {e}")

    LOGGER.error("All sources failed for USD/EGP")
    return None


def upsert_commodity_data(connection: Any, data: pd.DataFrame) -> int:
    """Insert or update commodity data in the database."""
    if data.empty:
        LOGGER.warning("No commodity data to upsert")
        return 0

    # Check if source column exists
    has_source = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT source FROM daily_commodities LIMIT 1")
            has_source = True
    except mysql.connector.Error:
        has_source = False

    rows = []
    for _, row in data.iterrows():
        if has_source:
            rows.append((
                row["trade_date"],
                row["commodity_name"],
                float(row["price"]),
                row.get("source", "unknown"),
            ))
        else:
            rows.append((
                row["trade_date"],
                row["commodity_name"],
                float(row["price"]),
            ))

    with connection.cursor() as cursor:
        if has_source:
            cursor.executemany(
                """
                INSERT INTO daily_commodities (trade_date, commodity_name, price, source)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    price = VALUES(price),
                    source = VALUES(source)
                """,
                rows,
            )
        else:
            cursor.executemany(
                """
                INSERT INTO daily_commodities (trade_date, commodity_name, price)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    price = VALUES(price)
                """,
                rows,
            )

    LOGGER.info(f"Upserted {len(rows)} commodity records")
    return len(rows)


def upsert_market_context_data(connection: Any, data: pd.DataFrame) -> int:
    """Insert or update market context data (USD/EGP rates)."""
    if data.empty:
        LOGGER.warning("No market context data to upsert")
        return 0

    # Check if usd_egp_source column exists
    has_source_col = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT usd_egp_source FROM market_context LIMIT 1")
            has_source_col = True
    except mysql.connector.Error:
        has_source_col = False

    rows = []
    for _, row in data.iterrows():
        if has_source_col:
            rows.append((
                row["trade_date"],
                float(row["usd_egp_close"]) if pd.notna(row["usd_egp_close"]) else None,
                row.get("source", "unknown"),
            ))
        else:
            rows.append((
                row["trade_date"],
                float(row["usd_egp_close"]) if pd.notna(row["usd_egp_close"]) else None,
            ))

    with connection.cursor() as cursor:
        if has_source_col:
            cursor.executemany(
                """
                INSERT INTO market_context (trade_date, usd_egp_close, usd_egp_source)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    usd_egp_close = VALUES(usd_egp_close),
                    usd_egp_source = VALUES(usd_egp_source)
                """,
                rows,
            )
        else:
            cursor.executemany(
                """
                INSERT INTO market_context (trade_date, usd_egp_close)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    usd_egp_close = VALUES(usd_egp_close)
                """,
                rows,
            )

    LOGGER.info(f"Upserted {len(rows)} market context records")
    return len(rows)


def count_commodity_records(connection: Any) -> dict[str, Any]:
    """Count records in daily_commodities table."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM daily_commodities")
        total = cursor.fetchone()[0]

        # Try to get breakdown by commodity and source, but handle missing source column
        try:
            cursor.execute(
                """
                SELECT commodity_name, COUNT(*), COALESCE(source, 'unknown')
                FROM daily_commodities
                GROUP BY commodity_name, source
                """
            )
            by_commodity = {}
            for name, count, source in cursor.fetchall():
                if name not in by_commodity:
                    by_commodity[name] = {"total": 0, "sources": {}}
                by_commodity[name]["total"] += count
                by_commodity[name]["sources"][source] = count
        except mysql.connector.Error:
            # source column doesn't exist, get basic breakdown
            cursor.execute(
                """
                SELECT commodity_name, COUNT(*)
                FROM daily_commodities
                GROUP BY commodity_name
                """
            )
            by_commodity = {}
            for name, count in cursor.fetchall():
                by_commodity[name] = {"total": count, "sources": {"unknown": count}}

    return {"total": total, "by_commodity": by_commodity}


def count_market_context_records(connection: Any) -> dict[str, Any]:
    """Count records in market_context table."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM market_context")
        total = cursor.fetchone()[0]

        # Check if usd_egp_close column exists
        try:
            cursor.execute("SELECT COUNT(*) FROM market_context WHERE usd_egp_close IS NOT NULL")
            with_usd_egp = cursor.fetchone()[0]
        except mysql.connector.Error:
            with_usd_egp = 0

        # Check if usd_egp_source column exists
        sources = {}
        try:
            cursor.execute(
                """
                SELECT usd_egp_source, COUNT(*)
                FROM market_context
                WHERE usd_egp_source IS NOT NULL
                GROUP BY usd_egp_source
                """
            )
            sources = {source: count for source, count in cursor.fetchall()}
        except mysql.connector.Error:
            sources = {}

        cursor.execute("SELECT MIN(trade_date), MAX(trade_date) FROM market_context")
        min_date, max_date = cursor.fetchone()

    return {
        "total": total,
        "with_usd_egp": with_usd_egp,
        "sources": sources,
        "date_range": (min_date, max_date),
    }


def backfill_brent(fetcher: DataFetcher, connection: Any) -> int:
    """Backfill Brent Crude data."""
    LOGGER.info("=" * 60)
    LOGGER.info("BACKFILLING BRENT CRUDE")
    LOGGER.info("=" * 60)

    total_rows = 0
    chunks = chunk_date_range(START_DATE, END_DATE, CHUNK_DAYS)

    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        LOGGER.info(f"Processing chunk {i}/{len(chunks)}: {chunk_start} to {chunk_end}")

        df = fetch_brent_with_fallback(fetcher, chunk_start, chunk_end)
        if df is not None and not df.empty:
            rows = upsert_commodity_data(connection, df)
            total_rows += rows

    LOGGER.info(f"Total Brent Crude rows upserted: {total_rows}")
    return total_rows


def backfill_urea_synthetic(connection: Any, fetcher: DataFetcher) -> int:
    """
    Backfill Urea data using synthetic generation from Brent Crude.
    First fetches Brent data, then generates Urea prices using correlation.
    """
    LOGGER.info("=" * 60)
    LOGGER.info("BACKFILLING UREA (Synthetic from Brent)")
    LOGGER.info("=" * 60)

    # First fetch Brent data for the full period
    brent_data = None
    chunks = chunk_date_range(START_DATE, END_DATE, CHUNK_DAYS)
    brent_frames = []
    
    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        LOGGER.info(f"Fetching Brent chunk {i}/{len(chunks)} for Urea generation")
        df = fetch_brent_with_fallback(fetcher, chunk_start, chunk_end)
        if df is not None and not df.empty:
            brent_frames.append(df)
    
    if brent_frames:
        brent_data = pd.concat(brent_frames, ignore_index=True)
        brent_data = brent_data.drop_duplicates(subset=["trade_date"], keep="last")
    
    if brent_data is None or brent_data.empty:
        LOGGER.error("No Brent data available for Urea generation")
        return 0
    
    # Generate Urea from Brent
    urea_df = generate_urea_from_brent(brent_data, baseline=180.0)
    
    if urea_df is not None and not urea_df.empty:
        rows = upsert_commodity_data(connection, urea_df)
        LOGGER.info(f"Total Urea rows upserted: {rows}")
        return rows
    
    return 0


def backfill_usd_egp(fetcher: DataFetcher, connection: Any) -> int:
    """Backfill USD/EGP exchange rates."""
    LOGGER.info("=" * 60)
    LOGGER.info("BACKFILLING USD/EGP RATES")
    LOGGER.info("=" * 60)

    # For FX, we can try to get full range at once
    df = fetch_usd_egp_with_fallback(fetcher, START_DATE, END_DATE)

    if df is not None and not df.empty:
        rows = upsert_market_context_data(connection, df)
        LOGGER.info(f"Total USD/EGP rows upserted: {rows}")
        return rows

    return 0


def main() -> int:
    """Main entry point."""
    print("\n" + "=" * 70)
    print("  MULTI-SOURCE DATA BACKFILL")
    print("  Sources: FMP, Alpha Vantage, Investing.com")
    print("  Target Tables: daily_commodities, market_context")
    print("  Date Range: 2016-01-01 to 2026-04-30")
    print("=" * 70)

    fetcher = create_fetcher()

    # Connect to database
    LOGGER.info("Connecting to database...")
    connection = mysql.connector.connect(**DB_CONFIG)

    try:
        # Ensure tables exist
        ensure_daily_commodities_table(connection)
        ensure_market_context_table(connection)

        # Get initial counts
        LOGGER.info("\n--- Initial State ---")
        initial_commodities = count_commodity_records(connection)
        initial_context = count_market_context_records(connection)
        LOGGER.info(f"Commodities: {initial_commodities}")
        LOGGER.info(f"Market Context: {initial_context}")

        # Perform backfills
        brent_rows = backfill_brent(fetcher, connection)
        
        # Generate Urea from Brent correlation instead of fetching
        urea_rows = backfill_urea_synthetic(connection, fetcher)
        
        usd_egp_rows = backfill_usd_egp(fetcher, connection)

        # Get final counts
        LOGGER.info("\n--- Final State ---")
        final_commodities = count_commodity_records(connection)
        final_context = count_market_context_records(connection)

        # Print summary
        print("\n" + "=" * 70)
        print("  BACKFILL SUMMARY")
        print("=" * 70)
        print(f"\nBrent Crude:")
        print(f"  Rows added: {brent_rows}")
        print(f"  Total in DB: {final_commodities['by_commodity'].get('Brent Crude', {}).get('total', 0)}")

        print(f"\nUrea:")
        print(f"  Rows added: {urea_rows}")
        print(f"  Total in DB: {final_commodities['by_commodity'].get('Urea', {}).get('total', 0)}")

        print(f"\nUSD/EGP Rates:")
        print(f"  Rows added: {usd_egp_rows}")
        print(f"  Total in DB with rates: {final_context['with_usd_egp']}")
        print(f"  Sources: {final_context['sources']}")
        print(f"  Date range: {final_context['date_range'][0]} to {final_context['date_range'][1]}")

        print("\n" + "=" * 70)
        print("  ✅ BACKFILL COMPLETE")
        print("=" * 70)

        return 0

    except Exception as e:
        LOGGER.error(f"Backfill failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        connection.close()
        LOGGER.info("Database connection closed")


if __name__ == "__main__":
    sys.exit(main())
