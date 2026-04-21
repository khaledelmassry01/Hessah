from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

import pandas as pd
import requests

import investpy
import investpy.stocks as investpy_stocks
import mysql.connector

try:
    import cloudscraper
except Exception:  # noqa: BLE001
    cloudscraper = None

LOGGER = logging.getLogger("db_seeder")
DEFAULT_FROM_DATE = "01/01/2016"
DEFAULT_BATCH_SIZE = 1000
DEFAULT_REQUEST_SLEEP_SECONDS = 2.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 15
DEFAULT_COVERAGE_WINDOW_DAYS = 14
DEFAULT_EODHD_BASE_URL = "https://eodhd.com/api/eod"
DEFAULT_EODHD_TIMEOUT_SECONDS = 30
INVESTPY_HTTP_CONFIGURED = False

SECTOR_NAMES = {
    "BANKS": "Banks",
    "FIN_SERV": "Financial Services",
    "INDUSTRIALS": "Industrials",
    "REAL_ESTATE": "Real Estate",
    "TELECOM": "Telecommunications",
    "ENERGY": "Energy",
    "CONSUMER": "Consumer Staples & Discretionary",
    "HEALTHCARE": "Healthcare",
    "MATERIALS": "Materials",
    "TECHNOLOGY": "Technology",
}


@dataclass(frozen=True)
class StockSeed:
    symbol: str
    name: str
    sector_code: str

    @property
    def base_symbol(self) -> str:
        if self.symbol.endswith(".CA"):
            return self.symbol[:-3]
        return self.symbol


@dataclass(frozen=True)
class TableMapping:
    table_name: str
    instrument_column: str
    trade_date_column: str
    open_column: str
    high_column: str
    low_column: str
    close_column: str
    volume_column: str
    halted_column: str | None

    def insert_columns(self) -> list[str]:
        columns = [
            self.instrument_column,
            self.trade_date_column,
            self.open_column,
            self.high_column,
            self.low_column,
            self.close_column,
            self.volume_column,
        ]
        if self.halted_column:
            columns.append(self.halted_column)
        return columns

    def insert_sql(self) -> str:
        columns = self.insert_columns()
        placeholders = ", ".join(["%s"] * len(columns))
        assignments = [
            f"{self.open_column}=VALUES({self.open_column})",
            f"{self.high_column}=VALUES({self.high_column})",
            f"{self.low_column}=VALUES({self.low_column})",
            f"{self.close_column}=VALUES({self.close_column})",
            f"{self.volume_column}=VALUES({self.volume_column})",
        ]
        if self.halted_column:
            assignments.append(f"{self.halted_column}=VALUES({self.halted_column})")

        return (
            f"INSERT INTO {self.table_name} ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {', '.join(assignments)}"
        )


@dataclass(frozen=True)
class HistoryCoverage:
    count: int
    min_trade_date: date | None
    max_trade_date: date | None


EGX30_STOCKS: list[StockSeed] = [
    StockSeed("COMI.CA", "Commercial International Bank", "BANKS"),
    StockSeed("HRHO.CA", "EFG Holding", "FIN_SERV"),
    StockSeed("SWDY.CA", "Elsewedy Electric", "INDUSTRIALS"),
    StockSeed("ETEL.CA", "Telecom Egypt", "TELECOM"),
    StockSeed("EFIH.CA", "eFinance Investment Group", "TECHNOLOGY"),
    StockSeed("ABUK.CA", "Abu Qir Fertilizers", "MATERIALS"),
    StockSeed("FWRY.CA", "Fawry", "TECHNOLOGY"),
    StockSeed("PHDC.CA", "Palm Hills Development", "REAL_ESTATE"),
    StockSeed("TMGH.CA", "Talaat Moustafa Group", "REAL_ESTATE"),
    StockSeed("ORWE.CA", "Oriental Weavers", "CONSUMER"),
    StockSeed("EAST.CA", "Eastern Company", "CONSUMER"),
    StockSeed("AMOC.CA", "Alexandria Mineral Oils", "ENERGY"),
    StockSeed("MFPC.CA", "Misr Fertilizers Production", "MATERIALS"),
    StockSeed("SKPC.CA", "Sidi Kerir Petrochemicals", "MATERIALS"),
    StockSeed("CCAP.CA", "Citadel Capital", "FIN_SERV"),
    StockSeed("HELI.CA", "Heliopolis Housing", "REAL_ESTATE"),
    StockSeed("ORAS.CA", "Orascom Construction", "INDUSTRIALS"),
    StockSeed("EKHO.CA", "Egypt Kuwait Holding", "INDUSTRIALS"),
    StockSeed("MICH.CA", "Misr Chemical Industries", "MATERIALS"),
    StockSeed("ALCN.CA", "Alexandria Containers", "INDUSTRIALS"),
    StockSeed("ORHD.CA", "Orascom Development Egypt", "REAL_ESTATE"),
    StockSeed("JUFO.CA", "Juhayna Food Industries", "CONSUMER"),
    StockSeed("DOMT.CA", "Domty", "CONSUMER"),
    StockSeed("GDWA.CA", "Gadwa for Industrial Development", "FIN_SERV"),
    StockSeed("CIEB.CA", "Credit Agricole Egypt", "BANKS"),
    StockSeed("AUTO.CA", "GB Corp", "CONSUMER"),
    StockSeed("BTFH.CA", "Beltone Holding", "FIN_SERV"),
    StockSeed("OBRI.CA", "Obour Land", "CONSUMER"),
    StockSeed("RAYA.CA", "Raya Holding", "TECHNOLOGY"),
    StockSeed("CLHO.CA", "Cleopatra Hospitals", "HEALTHCARE"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed EGX30 historical data from investpy into MySQL")
    parser.add_argument("--from-date", default=DEFAULT_FROM_DATE, help="Start date in dd/mm/yyyy format")
    parser.add_argument("--to-date", default=date.today().strftime("%d/%m/%Y"), help="End date in dd/mm/yyyy format")
    parser.add_argument("--db-endpoints", default="localhost:3307,mysql-db:3306")
    parser.add_argument("--db-user", default=os.getenv("DB_USER", "egx_app_user"))
    parser.add_argument("--db-password", default=os.getenv("DB_PASSWORD", ""))
    parser.add_argument("--db-name", default=os.getenv("DB_NAME", "egx_portfolio"))
    parser.add_argument("--eodhd-api-token", default=os.getenv("EODHD_API_TOKEN", ""))
    parser.add_argument("--request-sleep", type=float, default=DEFAULT_REQUEST_SLEEP_SECONDS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--coverage-window-days", type=int, default=DEFAULT_COVERAGE_WINDOW_DAYS)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def configure_investpy_http() -> None:
    global INVESTPY_HTTP_CONFIGURED
    if INVESTPY_HTTP_CONFIGURED:
        return

    if cloudscraper is None:
        LOGGER.warning("cloudscraper is unavailable; investpy may fail with HTTP 403")
        INVESTPY_HTTP_CONFIGURED = True
        return

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    def _post(url: str, headers: dict[str, str] | None = None, data: Any = None, **_: Any):
        return scraper.post(url, headers=headers, data=data, timeout=40)

    investpy_stocks.requests.post = _post
    INVESTPY_HTTP_CONFIGURED = True
    LOGGER.info("Configured investpy to use Cloudflare-aware HTTP session")


def parse_endpoints(raw: str) -> list[tuple[str, int]]:
    endpoints: list[tuple[str, int]] = []
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(f"Invalid endpoint '{token}'. Expected host:port")
        host, port_raw = token.rsplit(":", 1)
        endpoints.append((host.strip(), int(port_raw)))
    if not endpoints:
        raise ValueError("No MySQL endpoints provided")
    return endpoints


def connect_mysql(endpoints: Iterable[tuple[str, int]], user: str, password: str, database: str):
    last_error: Exception | None = None
    for host, port in endpoints:
        try:
            connection = mysql.connector.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connection_timeout=DEFAULT_CONNECT_TIMEOUT_SECONDS,
                autocommit=False,
            )
            LOGGER.info("Connected to MySQL at %s:%s", host, port)
            return connection
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            LOGGER.warning("Failed to connect to %s:%s (%s)", host, port, exc)

    if last_error:
        raise RuntimeError(f"Unable to connect to MySQL using provided endpoints: {last_error}") from last_error
    raise RuntimeError("Unable to connect to MySQL")


def parse_cli_date(raw: str, argument_name: str) -> date:
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ValueError(f"{argument_name} must be in dd/mm/yyyy format. Got: {raw}") from exc


def table_exists(cursor: Any, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = %s
        """,
        (table_name,),
    )
    row = cursor.fetchone()
    return bool(row and int(row[0]) > 0)


def get_table_columns(cursor: Any, table_name: str) -> set[str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s
        """,
        (table_name,),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def pick_column(columns: set[str], candidates: list[str], label: str) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise RuntimeError(f"Could not resolve column for {label}. Candidates={candidates}, available={sorted(columns)}")


def resolve_target_table(cursor: Any) -> TableMapping:
    if table_exists(cursor, "historical_market_data"):
        table_name = "historical_market_data"
    elif table_exists(cursor, "market_daily_bars"):
        table_name = "market_daily_bars"
    else:
        raise RuntimeError("Neither historical_market_data nor market_daily_bars exists")

    columns = get_table_columns(cursor, table_name)
    instrument_column = pick_column(columns, ["instrument_id", "stock_id"], "instrument id")
    trade_date_column = pick_column(columns, ["trade_date", "date"], "trade date")
    open_column = pick_column(columns, ["open_price", "open"], "open")
    high_column = pick_column(columns, ["high_price", "high"], "high")
    low_column = pick_column(columns, ["low_price", "low"], "low")
    close_column = pick_column(columns, ["close_price", "close"], "close")
    volume_column = pick_column(columns, ["volume", "trading_volume"], "volume")
    halted_column = None
    if "is_halted" in columns:
        halted_column = "is_halted"
    elif "halted" in columns:
        halted_column = "halted"

    mapping = TableMapping(
        table_name=table_name,
        instrument_column=instrument_column,
        trade_date_column=trade_date_column,
        open_column=open_column,
        high_column=high_column,
        low_column=low_column,
        close_column=close_column,
        volume_column=volume_column,
        halted_column=halted_column,
    )
    LOGGER.info("Using target table %s with instrument column %s", mapping.table_name, mapping.instrument_column)
    return mapping


def ensure_sectors(cursor: Any) -> None:
    sql = (
        "INSERT INTO sector_reference (code, name, is_active) "
        "VALUES (%s, %s, TRUE) "
        "ON DUPLICATE KEY UPDATE name=VALUES(name), is_active=TRUE"
    )
    rows = [(code, name) for code, name in SECTOR_NAMES.items()]
    cursor.executemany(sql, rows)


def get_or_create_instrument(cursor: Any, stock: StockSeed) -> int:
    cursor.execute("SELECT id FROM stock_instruments WHERE symbol=%s LIMIT 1", (stock.symbol,))
    row = cursor.fetchone()
    if row:
        return int(row[0])

    cursor.execute(
        """
        INSERT INTO stock_instruments (
            symbol, name, sector_code, last_price, is_suspended, suspension_reason
        ) VALUES (%s, %s, %s, %s, FALSE, NULL)
        ON DUPLICATE KEY UPDATE
            name=VALUES(name),
            sector_code=VALUES(sector_code),
            is_suspended=FALSE,
            suspension_reason=NULL
        """,
        (stock.symbol, stock.name, stock.sector_code, Decimal("0.0000")),
    )

    cursor.execute("SELECT id FROM stock_instruments WHERE symbol=%s LIMIT 1", (stock.symbol,))
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"Failed to create instrument for {stock.symbol}")
    return int(row[0])


def count_history_rows(cursor: Any, mapping: TableMapping, instrument_id: int) -> int:
    cursor.execute(
        f"SELECT COUNT(*) FROM {mapping.table_name} WHERE {mapping.instrument_column}=%s",
        (instrument_id,),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def get_history_coverage(cursor: Any, mapping: TableMapping, instrument_id: int) -> HistoryCoverage:
    cursor.execute(
        (
            f"SELECT COUNT(*), MIN({mapping.trade_date_column}), MAX({mapping.trade_date_column}) "
            f"FROM {mapping.table_name} "
            f"WHERE {mapping.instrument_column}=%s"
        ),
        (instrument_id,),
    )
    row = cursor.fetchone()
    if not row:
        return HistoryCoverage(count=0, min_trade_date=None, max_trade_date=None)

    min_trade_date = row[1]
    max_trade_date = row[2]
    return HistoryCoverage(
        count=int(row[0]),
        min_trade_date=min_trade_date,
        max_trade_date=max_trade_date,
    )


def has_full_coverage(
    coverage: HistoryCoverage,
    expected_start: date,
    expected_end: date,
    coverage_window_days: int,
) -> bool:
    if coverage.count <= 0:
        return False
    if coverage.min_trade_date is None or coverage.max_trade_date is None:
        return False

    latest_acceptable_gap = max(0, coverage_window_days)
    latest_required_date = expected_end - timedelta(days=latest_acceptable_gap)

    return (
        coverage.min_trade_date <= expected_start
        and coverage.max_trade_date >= latest_required_date
    )


def fetch_latest_close(cursor: Any, mapping: TableMapping, instrument_id: int) -> Decimal | None:
    cursor.execute(
        (
            f"SELECT {mapping.close_column} "
            f"FROM {mapping.table_name} "
            f"WHERE {mapping.instrument_column}=%s "
            f"ORDER BY {mapping.trade_date_column} DESC LIMIT 1"
        ),
        (instrument_id,),
    )
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return Decimal(str(row[0])).quantize(Decimal("0.0001"))


def update_last_price(cursor: Any, instrument_id: int, close_price: Decimal | None) -> None:
    if close_price is None:
        return
    cursor.execute(
        "UPDATE stock_instruments SET last_price=%s WHERE id=%s",
        (close_price, instrument_id),
    )


def fetch_history_from_investpy(stock: StockSeed, from_date: str, to_date: str) -> pd.DataFrame:
    configure_investpy_http()
    last_error: Exception | None = None

    direct_candidates = [stock.base_symbol, stock.symbol, stock.name]
    for candidate in direct_candidates:
        try:
            frame = investpy.get_stock_historical_data(
                stock=candidate,
                country="egypt",
                from_date=from_date,
                to_date=to_date,
            )
            normalized = normalize_history_frame(frame)
            if not normalized.empty:
                LOGGER.info("%s: fetched using get_stock_historical_data(stock=%s)", stock.symbol, candidate)
                return normalized
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    if last_error:
        raise RuntimeError(f"investpy fetch failed for {stock.symbol}: {last_error}") from last_error
    raise RuntimeError(f"investpy returned no data for {stock.symbol}")


def ticker_candidates(base_symbol: str) -> list[str]:
    candidates = [
        f"{base_symbol}.CA",
        f"{base_symbol}.CAI",
        f"{base_symbol}.EGX",
        base_symbol,
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def fetch_history_from_eodhd(
    stock: StockSeed,
    from_date: date,
    to_date: date,
    api_token: str,
) -> pd.DataFrame:
    if not api_token:
        raise RuntimeError("EODHD fallback is not configured: missing API token")

    last_error: Exception | None = None
    for ticker in ticker_candidates(stock.base_symbol):
        try:
            response = requests.get(
                f"{DEFAULT_EODHD_BASE_URL}/{ticker}",
                params={
                    "api_token": api_token,
                    "fmt": "json",
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                },
                timeout=DEFAULT_EODHD_TIMEOUT_SECONDS,
            )

            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                body = response.text[:200]
                raise RuntimeError(f"HTTP {response.status_code}: {body}")

            payload = response.json()
            frame = normalize_eodhd_frame(payload)
            if frame.empty:
                continue

            LOGGER.info("%s: fetched using EODHD ticker %s", stock.symbol, ticker)
            return frame
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    if last_error:
        raise RuntimeError(f"EODHD fallback failed for {stock.symbol}: {last_error}") from last_error
    raise RuntimeError(f"EODHD fallback returned no data for {stock.symbol}")


def normalize_eodhd_frame(raw_payload: Any) -> pd.DataFrame:
    if not isinstance(raw_payload, list) or not raw_payload:
        return pd.DataFrame()

    frame = pd.DataFrame(raw_payload)
    if frame.empty:
        return pd.DataFrame()

    lower_map = {str(column).strip().lower(): column for column in frame.columns}
    date_column = lower_map.get("date")
    close_column = lower_map.get("close")
    if date_column is None or close_column is None:
        return pd.DataFrame()

    open_column = lower_map.get("open")
    high_column = lower_map.get("high")
    low_column = lower_map.get("low")
    volume_column = lower_map.get("volume")

    out = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(frame[date_column], errors="coerce"),
            "open_price": pd.to_numeric(frame[open_column], errors="coerce") if open_column else pd.NA,
            "high_price": pd.to_numeric(frame[high_column], errors="coerce") if high_column else pd.NA,
            "low_price": pd.to_numeric(frame[low_column], errors="coerce") if low_column else pd.NA,
            "close_price": pd.to_numeric(frame[close_column], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_column], errors="coerce") if volume_column else 0,
        }
    )

    out = out.dropna(subset=["trade_date", "close_price"])
    if out.empty:
        return pd.DataFrame()

    out["open_price"] = out["open_price"].fillna(out["close_price"])
    out["high_price"] = out["high_price"].fillna(out["close_price"])
    out["low_price"] = out["low_price"].fillna(out["close_price"])
    out["volume"] = out["volume"].fillna(0).clip(lower=0)

    out["high_price"] = out[["open_price", "high_price", "low_price", "close_price"]].max(axis=1)
    out["low_price"] = out[["open_price", "high_price", "low_price", "close_price"]].min(axis=1)

    out["trade_date"] = out["trade_date"].dt.date
    out = out.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")

    return out[["trade_date", "open_price", "high_price", "low_price", "close_price", "volume"]]


def fetch_history_with_fallback(
    stock: StockSeed,
    from_date_str: str,
    to_date_str: str,
    from_date_obj: date,
    to_date_obj: date,
    eodhd_api_token: str,
) -> tuple[pd.DataFrame, str]:
    try:
        return fetch_history_from_investpy(stock, from_date_str, to_date_str), "investpy"
    except Exception as investpy_error:  # noqa: BLE001
        LOGGER.warning("%s investpy failed (%s). Trying EODHD fallback.", stock.symbol, investpy_error)

    frame = fetch_history_from_eodhd(
        stock=stock,
        from_date=from_date_obj,
        to_date=to_date_obj,
        api_token=eodhd_api_token,
    )
    return frame, "eodhd"


def normalize_history_frame(raw_frame: Any) -> pd.DataFrame:
    if raw_frame is None:
        return pd.DataFrame()

    frame = pd.DataFrame(raw_frame).copy()
    if frame.empty:
        return pd.DataFrame()

    # investpy returns Date as index in most cases; normalize to an explicit column.
    frame = frame.reset_index()
    lower_map = {str(column).strip().lower(): column for column in frame.columns}

    date_column = lower_map.get("date")
    if date_column is None:
        date_column = frame.columns[0]

    open_column = lower_map.get("open")
    high_column = lower_map.get("high")
    low_column = lower_map.get("low")
    close_column = lower_map.get("close")
    volume_column = lower_map.get("volume")

    if close_column is None:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(frame[date_column], errors="coerce"),
            "open_price": pd.to_numeric(frame[open_column], errors="coerce") if open_column else pd.NA,
            "high_price": pd.to_numeric(frame[high_column], errors="coerce") if high_column else pd.NA,
            "low_price": pd.to_numeric(frame[low_column], errors="coerce") if low_column else pd.NA,
            "close_price": pd.to_numeric(frame[close_column], errors="coerce"),
            "volume": pd.to_numeric(frame[volume_column], errors="coerce") if volume_column else 0,
        }
    )

    out = out.dropna(subset=["trade_date", "close_price"])
    if out.empty:
        return pd.DataFrame()

    out["open_price"] = out["open_price"].fillna(out["close_price"])
    out["high_price"] = out["high_price"].fillna(out["close_price"])
    out["low_price"] = out["low_price"].fillna(out["close_price"])

    out["volume"] = out["volume"].fillna(0).clip(lower=0)

    # Ensure OHLC relationship is always coherent.
    out["high_price"] = out[["open_price", "high_price", "low_price", "close_price"]].max(axis=1)
    out["low_price"] = out[["open_price", "high_price", "low_price", "close_price"]].min(axis=1)

    out["trade_date"] = out["trade_date"].dt.date
    out = out.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")

    return out[["trade_date", "open_price", "high_price", "low_price", "close_price", "volume"]]


def as_price(value: Any) -> Decimal:
    return Decimal(str(round(float(value), 4))).quantize(Decimal("0.0001"))


def build_rows(frame: pd.DataFrame, instrument_id: int, mapping: TableMapping) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for _, row in frame.iterrows():
        payload = [
            instrument_id,
            row["trade_date"],
            as_price(row["open_price"]),
            as_price(row["high_price"]),
            as_price(row["low_price"]),
            as_price(row["close_price"]),
            int(max(0, float(row["volume"]))),
        ]
        if mapping.halted_column:
            payload.append(False)
        rows.append(tuple(payload))
    return rows


def execute_batch_insert(cursor: Any, sql: str, rows: list[tuple[Any, ...]], batch_size: int) -> None:
    if not rows:
        return
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        cursor.executemany(sql, chunk)


def run() -> dict[str, Any]:
    args = parse_args()
    from_date_obj = parse_cli_date(args.from_date, "--from-date")
    to_date_obj = parse_cli_date(args.to_date, "--to-date")
    if from_date_obj > to_date_obj:
        raise ValueError("--from-date must be earlier than or equal to --to-date")

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    endpoints = parse_endpoints(args.db_endpoints)
    conn = connect_mysql(endpoints, args.db_user, args.db_password, args.db_name)

    summary: dict[str, Any] = {
        "fromDate": args.from_date,
        "toDate": args.to_date,
        "targetTable": None,
        "symbolsTotal": len(EGX30_STOCKS),
        "symbolsSeeded": 0,
        "symbolsSkipped": 0,
        "symbolsFailed": 0,
        "rowsInserted": 0,
        "rowsUpserted": 0,
        "sourceBreakdown": {"investpy": 0, "eodhd": 0},
        "missingSymbols": [],
    }

    cursor = conn.cursor()
    try:
        mapping = resolve_target_table(cursor)
        summary["targetTable"] = mapping.table_name

        ensure_sectors(cursor)
        conn.commit()

        insert_sql = mapping.insert_sql()

        for index, stock in enumerate(EGX30_STOCKS, start=1):
            LOGGER.info("[%s/%s] Processing %s", index, len(EGX30_STOCKS), stock.symbol)
            requested_history = False
            try:
                instrument_id = get_or_create_instrument(cursor, stock)
                existing_coverage = get_history_coverage(cursor, mapping, instrument_id)

                if has_full_coverage(
                    coverage=existing_coverage,
                    expected_start=from_date_obj,
                    expected_end=to_date_obj,
                    coverage_window_days=args.coverage_window_days,
                ):
                    latest_close = fetch_latest_close(cursor, mapping, instrument_id)
                    update_last_price(cursor, instrument_id, latest_close)
                    conn.commit()
                    summary["symbolsSkipped"] += 1
                    LOGGER.info(
                        "%s skipped (resume mode): rows=%s coverage=%s..%s",
                        stock.symbol,
                        existing_coverage.count,
                        existing_coverage.min_trade_date,
                        existing_coverage.max_trade_date,
                    )
                    continue

                requested_history = True
                frame, source_used = fetch_history_with_fallback(
                    stock=stock,
                    from_date_str=args.from_date,
                    to_date_str=args.to_date,
                    from_date_obj=from_date_obj,
                    to_date_obj=to_date_obj,
                    eodhd_api_token=args.eodhd_api_token,
                )
                if frame.empty:
                    raise RuntimeError("No historical rows returned by investpy")

                rows = build_rows(frame, instrument_id, mapping)
                execute_batch_insert(cursor, insert_sql, rows, max(1, args.batch_size))

                latest_close = as_price(frame.iloc[-1]["close_price"])
                update_last_price(cursor, instrument_id, latest_close)
                conn.commit()

                post_coverage = get_history_coverage(cursor, mapping, instrument_id)
                inserted_now = max(0, post_coverage.count - existing_coverage.count)
                summary["symbolsSeeded"] += 1
                summary["rowsInserted"] += inserted_now
                summary["rowsUpserted"] += len(rows)
                summary["sourceBreakdown"][source_used] += 1

                LOGGER.info(
                    "%s seeded successfully via %s: upserted=%s inserted=%s coverage=%s..%s latest_close=%s",
                    stock.symbol,
                    source_used,
                    len(rows),
                    inserted_now,
                    post_coverage.min_trade_date,
                    post_coverage.max_trade_date,
                    latest_close,
                )
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                summary["symbolsFailed"] += 1
                summary["missingSymbols"].append(stock.symbol)
                LOGGER.exception("%s failed: %s", stock.symbol, exc)
            finally:
                if requested_history and index < len(EGX30_STOCKS):
                    time.sleep(max(0.0, args.request_sleep))

        placeholders = ",".join(["%s"] * len(EGX30_STOCKS))
        symbol_values = [stock.symbol for stock in EGX30_STOCKS]

        cursor.execute(
            f"SELECT COUNT(*) FROM stock_instruments WHERE symbol IN ({placeholders})",
            tuple(symbol_values),
        )
        summary["instrumentRowsPresent"] = int(cursor.fetchone()[0])

        cursor.execute(
            (
                f"SELECT COUNT(DISTINCT {mapping.instrument_column}) "
                f"FROM {mapping.table_name} "
                f"WHERE {mapping.instrument_column} IN "
                f"(SELECT id FROM stock_instruments WHERE symbol IN ({placeholders}))"
            ),
            tuple(symbol_values),
        )
        summary["historySymbolsPresent"] = int(cursor.fetchone()[0])

        cursor.execute(
            (
                f"SELECT COUNT(*) "
                f"FROM {mapping.table_name} "
                f"WHERE {mapping.instrument_column} IN "
                f"(SELECT id FROM stock_instruments WHERE symbol IN ({placeholders}))"
            ),
            tuple(symbol_values),
        )
        summary["historyRowsTotalForEgx30"] = int(cursor.fetchone()[0])

        cursor.execute(
            (
                "SELECT si.symbol "
                "FROM stock_instruments si "
                "LEFT JOIN "
                f"(SELECT DISTINCT {mapping.instrument_column} AS instrument_id FROM {mapping.table_name}) h "
                "ON h.instrument_id = si.id "
                f"WHERE si.symbol IN ({placeholders}) AND h.instrument_id IS NULL "
                "ORDER BY si.symbol"
            ),
            tuple(symbol_values),
        )
        summary["symbolsWithoutHistory"] = [str(row[0]) for row in cursor.fetchall()]

        conn.commit()
        return summary
    finally:
        cursor.close()
        conn.close()


def main() -> int:
    summary = run()
    print(json.dumps(summary, indent=2, sort_keys=True))

    if summary.get("symbolsFailed", 0) > 0:
        return 1
    if summary.get("symbolsWithoutHistory"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
