from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from .feature_engineering import MysqlSettings, open_mysql_connection, resolve_mysql_settings

LOGGER = logging.getLogger(__name__)

USD_EGP_TICKER = "EGP=X"
GOLD_TICKER = "GC=F"
DEFAULT_START_DATE = date(2016, 1, 1)

# Manual lookup for CBE policy rate changes. Values are percent points.
# Source intended: historical CBE MPC decisions; can be replaced by official scrape later.
CBE_RATE_EVENTS: list[tuple[str, float]] = [
    ("2016-01-01", 10.75),
    ("2016-03-17", 10.75),
    ("2016-11-03", 14.75),
    ("2016-11-17", 15.75),
    ("2017-05-21", 16.75),
    ("2017-07-06", 18.75),
    ("2018-02-15", 17.75),
    ("2018-03-29", 16.75),
    ("2019-02-14", 15.75),
    ("2019-08-22", 14.75),
    ("2019-09-26", 13.75),
    ("2020-03-16", 9.25),
    ("2020-09-24", 8.75),
    ("2022-03-21", 9.25),
    ("2022-05-19", 11.25),
    ("2022-10-27", 13.25),
    ("2022-12-22", 16.25),
    ("2023-03-30", 18.25),
    ("2024-02-01", 21.25),
    ("2024-03-07", 27.25),
]

# EGX30 sector mapping using existing sector_reference codes in DB.
EGX30_SECTOR_MAP: dict[str, str] = {
    "COMI.CA": "BANKS",
    "CIEB.CA": "BANKS",
    "HRHO.CA": "FIN_SERV",
    "BTFH.CA": "FIN_SERV",
    "CCAP.CA": "FIN_SERV",
    "GDWA.CA": "FIN_SERV",
    "SWDY.CA": "INDUSTRIALS",
    "ORAS.CA": "INDUSTRIALS",
    "EKHO.CA": "INDUSTRIALS",
    "ALCN.CA": "INDUSTRIALS",
    "ETEL.CA": "TELECOM",
    "EFIH.CA": "TECHNOLOGY",
    "FWRY.CA": "TECHNOLOGY",
    "RAYA.CA": "TECHNOLOGY",
    "ABUK.CA": "MATERIALS",
    "MFPC.CA": "MATERIALS",
    "SKPC.CA": "MATERIALS",
    "MICH.CA": "MATERIALS",
    "AMOC.CA": "ENERGY",
    "PHDC.CA": "REAL_ESTATE",
    "TMGH.CA": "REAL_ESTATE",
    "HELI.CA": "REAL_ESTATE",
    "ORHD.CA": "REAL_ESTATE",
    "ORWE.CA": "CONSUMER",
    "EAST.CA": "CONSUMER",
    "JUFO.CA": "CONSUMER",
    "DOMT.CA": "CONSUMER",
    "AUTO.CA": "CONSUMER",
    "OBRI.CA": "CONSUMER",
    "CLHO.CA": "HEALTHCARE",
}


@dataclass(frozen=True)
class MacroSyncSummary:
    status: str
    trade_dates: int
    market_context_rows_upserted: int
    sector_rows_updated: int
    cbe_lookup_rows: int
    start_date: str
    end_date: str


def ensure_market_context_table(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS market_context (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                trade_date DATE NOT NULL,
                usd_egp_close DECIMAL(19, 6) NULL,
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


def ensure_cbe_lookup_table(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cbe_interest_rate_lookup (
                effective_date DATE NOT NULL PRIMARY KEY,
                policy_rate_pct DECIMAL(9, 4) NOT NULL,
                source VARCHAR(64) NOT NULL DEFAULT 'manual',
                note VARCHAR(255) NULL,
                created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                    ON UPDATE CURRENT_TIMESTAMP(6)
            ) ENGINE=InnoDB
            """
        )


def build_cbe_lookup_frame() -> pd.DataFrame:
    frame = pd.DataFrame(CBE_RATE_EVENTS, columns=["effective_date", "policy_rate_pct"])
    frame["effective_date"] = pd.to_datetime(frame["effective_date"], errors="coerce")
    frame["policy_rate_pct"] = pd.to_numeric(frame["policy_rate_pct"], errors="coerce")
    frame = frame.dropna(subset=["effective_date", "policy_rate_pct"]).sort_values("effective_date")
    frame["effective_date"] = frame["effective_date"].dt.normalize()
    frame = frame.drop_duplicates(subset=["effective_date"], keep="last").reset_index(drop=True)
    return frame


def sync_cbe_lookup(connection: Any, lookup_frame: pd.DataFrame) -> int:
    rows = []
    for _, item in lookup_frame.iterrows():
        rows.append((
            item["effective_date"].date(),
            float(item["policy_rate_pct"]),
            "manual",
            "CBE policy rate event",
        ))

    if not rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO cbe_interest_rate_lookup (
                effective_date,
                policy_rate_pct,
                source,
                note
            ) VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                policy_rate_pct = VALUES(policy_rate_pct),
                source = VALUES(source),
                note = VALUES(note)
            """,
            rows,
        )
    return len(rows)


def load_trade_dates(connection: Any, start_date: date, end_date: date | None) -> pd.DatetimeIndex:
    sql = [
        "SELECT DISTINCT trade_date",
        "FROM market_daily_bars",
        "WHERE trade_date >= %s",
    ]
    params: list[Any] = [start_date]

    if end_date is not None:
        sql.append("  AND trade_date <= %s")
        params.append(end_date)

    sql.append("ORDER BY trade_date ASC")

    with connection.cursor() as cursor:
        cursor.execute("\n".join(sql), tuple(params))
        rows = cursor.fetchall()

    dates = pd.to_datetime([item[0] for item in rows], errors="coerce")
    dates = dates[~dates.isna()]
    if len(dates) == 0:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(dates).normalize()


def _download_series(ticker: str, start_date: date, end_date: date | None, column_name: str) -> pd.DataFrame:
    start_value = pd.Timestamp(start_date)
    end_value = pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize() + pd.Timedelta(days=1)

    raw = yf.download(
        tickers=ticker,
        start=start_value.strftime("%Y-%m-%d"),
        end=end_value.strftime("%Y-%m-%d"),
        auto_adjust=False,
        progress=False,
        interval="1d",
        group_by="column",
        threads=False,
    )

    if raw is None or raw.empty:
        raise RuntimeError(f"No data returned by yfinance for {ticker}")

    close_values: pd.Series
    if isinstance(raw.columns, pd.MultiIndex):
        if ("Close", ticker) in raw.columns:
            close_values = raw[("Close", ticker)]
        else:
            close_slice = raw.xs("Close", axis=1, level=0, drop_level=True)
            if isinstance(close_slice, pd.DataFrame):
                if close_slice.empty:
                    raise RuntimeError(f"Close column missing from yfinance response for {ticker}")
                close_values = close_slice.iloc[:, 0]
            else:
                close_values = close_slice
    else:
        if "Close" not in raw.columns:
            raise RuntimeError(f"Close column missing from yfinance response for {ticker}")
        close_column = raw["Close"]
        if isinstance(close_column, pd.DataFrame):
            if close_column.empty:
                raise RuntimeError(f"Close column missing from yfinance response for {ticker}")
            close_values = close_column.iloc[:, 0]
        else:
            close_values = close_column

    series = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw.index, errors="coerce").normalize(),
            column_name: pd.to_numeric(close_values, errors="coerce"),
        }
    )
    series = series.dropna(subset=["trade_date"]).drop_duplicates(subset=["trade_date"], keep="last")
    return series.sort_values("trade_date").reset_index(drop=True)


def build_market_context_frame(trade_dates: pd.DatetimeIndex, start_date: date, end_date: date | None) -> pd.DataFrame:
    if len(trade_dates) == 0:
        return pd.DataFrame(columns=[
            "trade_date",
            "usd_egp_close",
            "gold_usd_close",
            "cbe_policy_rate_pct",
            "cbe_rate_changed",
        ])

    usd_frame = _download_series(USD_EGP_TICKER, start_date, end_date, "usd_egp_close")
    gold_frame = _download_series(GOLD_TICKER, start_date, end_date, "gold_usd_close")

    calendar = pd.DataFrame({"trade_date": trade_dates})
    calendar["trade_date"] = pd.to_datetime(calendar["trade_date"], errors="coerce")
    merged = calendar.merge(usd_frame, on="trade_date", how="left")
    merged = merged.merge(gold_frame, on="trade_date", how="left")
    merged[["usd_egp_close", "gold_usd_close"]] = merged[["usd_egp_close", "gold_usd_close"]].ffill().bfill()

    lookup = build_cbe_lookup_frame()
    lookup["effective_date"] = pd.to_datetime(lookup["effective_date"], errors="coerce")
    lookup = lookup.dropna(subset=["effective_date", "policy_rate_pct"]).sort_values("effective_date")

    cbe_daily = merged[["trade_date"]].sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")
    cbe_daily = cbe_daily.merge(
        lookup.rename(columns={"effective_date": "trade_date", "policy_rate_pct": "policy_rate_event"}),
        on="trade_date",
        how="left",
    )
    cbe_daily["policy_rate_pct"] = pd.to_numeric(cbe_daily["policy_rate_event"], errors="coerce").ffill().bfill()
    cbe_daily["cbe_rate_changed"] = cbe_daily["policy_rate_event"].notna()
    cbe_daily = cbe_daily.drop(columns=["policy_rate_event"])

    merged = merged.merge(cbe_daily, on="trade_date", how="left")
    merged["cbe_policy_rate_pct"] = pd.to_numeric(merged["policy_rate_pct"], errors="coerce").ffill().bfill()
    merged["cbe_rate_changed"] = merged["cbe_rate_changed"].fillna(False).astype(bool)
    merged = merged.drop(columns=["policy_rate_pct"])

    return merged.sort_values("trade_date").reset_index(drop=True)


def upsert_market_context(connection: Any, context_frame: pd.DataFrame) -> int:
    if context_frame.empty:
        return 0

    rows = []
    for _, item in context_frame.iterrows():
        rows.append(
            (
                item["trade_date"].date(),
                _maybe_float(item.get("usd_egp_close")),
                _maybe_float(item.get("gold_usd_close")),
                _maybe_float(item.get("cbe_policy_rate_pct")),
                bool(item.get("cbe_rate_changed", False)),
            )
        )

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO market_context (
                trade_date,
                usd_egp_close,
                gold_usd_close,
                cbe_policy_rate_pct,
                cbe_rate_changed
            ) VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                usd_egp_close = VALUES(usd_egp_close),
                gold_usd_close = VALUES(gold_usd_close),
                cbe_policy_rate_pct = VALUES(cbe_policy_rate_pct),
                cbe_rate_changed = VALUES(cbe_rate_changed)
            """,
            rows,
        )
    return len(rows)


def sync_sector_mapping(connection: Any) -> int:
    updated = 0
    with connection.cursor() as cursor:
        for canonical_symbol, sector_code in EGX30_SECTOR_MAP.items():
            base_symbol = canonical_symbol.split(".")[0]
            cursor.execute(
                """
                UPDATE stock_instruments
                SET sector_code = %s
                WHERE UPPER(symbol) IN (%s, %s)
                """,
                (sector_code, canonical_symbol.upper(), base_symbol.upper()),
            )
            updated += int(cursor.rowcount)
    return updated


def run_macro_enrichment(
    start_date: date = DEFAULT_START_DATE,
    end_date: date | None = None,
    settings: MysqlSettings | None = None,
) -> MacroSyncSummary:
    connection = open_mysql_connection(settings=settings)
    try:
        ensure_market_context_table(connection)
        ensure_cbe_lookup_table(connection)

        lookup_frame = build_cbe_lookup_frame()
        cbe_rows = sync_cbe_lookup(connection, lookup_frame)

        trade_dates = load_trade_dates(connection, start_date=start_date, end_date=end_date)
        if len(trade_dates) == 0:
            raise RuntimeError("No market_daily_bars rows were found for the selected date range")

        context_frame = build_market_context_frame(
            trade_dates=trade_dates,
            start_date=start_date,
            end_date=end_date,
        )
        context_rows = upsert_market_context(connection, context_frame)
        sector_rows = sync_sector_mapping(connection)

        first_date = context_frame["trade_date"].min().date().isoformat() if not context_frame.empty else ""
        last_date = context_frame["trade_date"].max().date().isoformat() if not context_frame.empty else ""

        return MacroSyncSummary(
            status="SUCCESS",
            trade_dates=len(trade_dates),
            market_context_rows_upserted=context_rows,
            sector_rows_updated=sector_rows,
            cbe_lookup_rows=cbe_rows,
            start_date=first_date,
            end_date=last_date,
        )
    finally:
        connection.close()


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:  # noqa: BLE001
        pass
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _build_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync EGX macro context and sector mapping")
    parser.add_argument("--start-date", type=str, default=DEFAULT_START_DATE.isoformat())
    parser.add_argument("--end-date", type=str, default="")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _build_cli_args()

    summary = run_macro_enrichment(
        start_date=_parse_iso_date(args.start_date) or DEFAULT_START_DATE,
        end_date=_parse_iso_date(args.end_date),
        settings=resolve_mysql_settings(),
    )

    LOGGER.info(
        "Macro sync complete status=%s trade_dates=%s context_rows=%s sectors_updated=%s range=%s..%s cbe_lookup_rows=%s",
        summary.status,
        summary.trade_dates,
        summary.market_context_rows_upserted,
        summary.sector_rows_updated,
        summary.start_date,
        summary.end_date,
        summary.cbe_lookup_rows,
    )


if __name__ == "__main__":
    main()
