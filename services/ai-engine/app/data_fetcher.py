"""
Multi-Source Data Fetcher Module
Integrates TradingView, Investing.com, Alpha Vantage, and Financial Modeling Prep (FMP)
with fallback chain logic for resilient data retrieval.

TradingView (tvdatafeed) is the primary source for EGX stock OHLCV data.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd
import requests
from tvDatafeed import TvDatafeed, Interval

LOGGER = logging.getLogger(__name__)

# API Keys
ALPHA_VANTAGE_API_KEY = "HEDCR99YILNP6A4A"
FMP_API_KEY = "8ID9U3FQCVXMxIJms5jmQxRtQMUBl4aV"
EODHD_API_KEY = "69e67350a20f86.57807831"

# API Endpoints
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
EODHD_BASE_URL = "https://eodhd.com/api"

# Source priority for fallback chain
FALLBACK_CHAIN = {
    "egx_stocks": ["tradingview", "eodhd", "investing_com", "yfinance"],
    "brent_crude": ["tradingview", "eodhd", "fmp", "yfinance", "investing_com"],
    "urea": ["investing_com", "yfinance"],
    "technical_indicators": ["alpha_vantage", "fmp"],
    "usd_egp": ["tradingview", "alpha_vantage", "yfinance"],
    "gold": ["alpha_vantage", "yfinance"],
    "sp500": ["fmp", "alpha_vantage", "yfinance"],
}


@dataclass
class FetchResult:
    """Result wrapper for data fetching operations."""

    success: bool
    data: pd.DataFrame | None
    source: str
    error_message: str | None = None
    rows_fetched: int = 0


class RateLimiter:
    """Simple rate limiter to prevent API throttling."""

    def __init__(self, calls_per_minute: int = 5):
        self.min_interval = 60.0 / calls_per_minute
        self.last_call_time: float | None = None

    def wait(self) -> None:
        """Wait if necessary to respect rate limits."""
        if self.last_call_time is not None:
            elapsed = time.time() - self.last_call_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()


# Global rate limiters
alpha_vantage_limiter = RateLimiter(calls_per_minute=5)  # Free tier: 5 calls/min
fmp_limiter = RateLimiter(calls_per_minute=10)  # FMP has higher limits
investing_limiter = RateLimiter(calls_per_minute=3)  # Be gentle with investing.com
eodhd_limiter = RateLimiter(calls_per_minute=20)  # EODHD generous limits
tradingview_limiter = RateLimiter(calls_per_minute=40)  # TradingView anonymous mode allows ~40/min


class DataFetcher:
    """
    Multi-source data fetcher with fallback chain logic.

    Primary sources:
    - EODHD: EGX Stocks (via GDRs), Brent Crude (via BNO ETF)
    - Investing.com: Urea Prices, EGX fallback
    - Alpha Vantage: Technical Indicators, Currency/Gold rates
    - FMP: Global Macro Data (S&P 500, Brent fallback), Company financials
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self._tv: TvDatafeed | None = None  # Lazy-initialised TradingView client

    # ==================== TradingView Methods ====================

    def _get_tv_client(self) -> TvDatafeed:
        """Lazy-initialise an anonymous TradingView connection."""
        if self._tv is None:
            LOGGER.info("Initialising TradingView anonymous connection")
            self._tv = TvDatafeed()
        return self._tv

    def fetch_symbol_data_tradingview(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        n_bars: int = 5000,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from TradingView for a given symbol.

        Handles EGX symbol translation (.CA suffix removal) and returns
        a DataFrame with DatetimeIndex and lowercase OHLCV columns matching
        the internal data_pipeline schema.

        Args:
            symbol: EGX symbol in Reuters/Yahoo format (e.g. 'COMI.CA', 'HRHO.CA')
            start_date: Optional start date filter
            end_date: Optional end date filter
            n_bars: Number of bars to request from TradingView (default 5000)

        Returns:
            DataFrame with DatetimeIndex and columns [open, high, low, close, volume].
            Returns empty DataFrame on failure (never raises).
        """
        tradingview_limiter.wait()

        # Symbol translation: strip .CA suffix for TradingView, use EGX exchange
        tv_symbol = symbol.replace(".CA", "") if symbol.endswith(".CA") else symbol
        tv_exchange = "EGX"

        try:
            tv = self._get_tv_client()
            LOGGER.info(f"TradingView fetch: symbol={tv_symbol} exchange={tv_exchange} n_bars={n_bars}")

            df = tv.get_hist(
                symbol=tv_symbol,
                exchange=tv_exchange,
                interval=Interval.in_daily,
                n_bars=n_bars,
            )

            if df is None or df.empty:
                LOGGER.error(f"TradingView returned empty data for {symbol}")
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

            # Drop the 'symbol' column that TradingView includes
            if "symbol" in df.columns:
                df = df.drop(columns=["symbol"])

            # Rename columns to match internal pipeline schema (lowercase)
            # TradingView returns: open, high, low, close, volume (already lowercase)
            column_map = {
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
            df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})

            # Ensure DatetimeIndex is timezone-naive
            if isinstance(df.index, pd.DatetimeIndex):
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
            else:
                df.index = pd.to_datetime(df.index, errors="coerce")
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)

            df = df.sort_index()

            # Filter to requested date range
            if start_date is not None:
                start_ts = pd.Timestamp(start_date)
                df = df.loc[df.index >= start_ts]
            if end_date is not None:
                end_ts = pd.Timestamp(end_date)
                df = df.loc[df.index <= end_ts]

            LOGGER.info(
                f"TradingView fetched {len(df)} bars for {symbol} "
                f"({df.index.min().date() if len(df) else 'N/A'} to {df.index.max().date() if len(df) else 'N/A'})"
            )
            return df[["open", "high", "low", "close", "volume"]]

        except Exception as e:
            LOGGER.error(f"TradingView fetch failed for {symbol}: {e}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def _fetch_tradingview_egx(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> FetchResult:
        """
        Fetch EGX stock from TradingView, returning a FetchResult compatible
        with the fallback chain.

        Args:
            symbol: Internal EGX symbol (e.g. 'COMI.CA')
            from_date: Start date
            to_date: End date

        Returns:
            FetchResult with OHLCV data
        """
        try:
            df = self.fetch_symbol_data_tradingview(
                symbol=symbol,
                start_date=from_date,
                end_date=to_date,
            )

            if df.empty:
                return FetchResult(
                    success=False, data=None, source="tradingview",
                    error_message=f"No TradingView data for {symbol}",
                )

            # Convert to FetchResult schema: trade_date column + lowercase OHLCV
            df = df.reset_index()
            date_col = df.columns[0]  # The former DatetimeIndex, usually 'datetime'
            df = df.rename(columns={date_col: "trade_date"})

            return FetchResult(
                success=True, data=df, source="tradingview", rows_fetched=len(df),
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="tradingview",
                error_message=f"TradingView error: {e}",
            )

    # ==================== Alpha Vantage Methods ====================

    def fetch_alpha_vantage_rsi(
        self,
        symbol: str,
        interval: str = "daily",
        time_period: int = 14,
        series_type: str = "close",
    ) -> FetchResult:
        """
        Fetch RSI technical indicator from Alpha Vantage.

        Args:
            symbol: Stock symbol (e.g., "SPY")
            interval: Time interval (daily, weekly, monthly)
            time_period: RSI calculation period
            series_type: Price type (close, open, high, low)

        Returns:
            FetchResult with RSI data or error
        """
        alpha_vantage_limiter.wait()

        params = {
            "function": "RSI",
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": series_type,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }

        try:
            LOGGER.info(f"Fetching RSI from Alpha Vantage for {symbol}")
            response = self.session.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Check for API error messages
            if "Error Message" in data:
                return FetchResult(
                    success=False,
                    data=None,
                    source="alpha_vantage",
                    error_message=data["Error Message"],
                )

            # Check for rate limit note
            if "Note" in data and "API call frequency" in data["Note"]:
                return FetchResult(
                    success=False,
                    data=None,
                    source="alpha_vantage",
                    error_message=f"Rate limited: {data['Note']}",
                )

            # Parse Technical Analysis data
            ta_key = "Technical Analysis: RSI"
            if ta_key not in data:
                return FetchResult(
                    success=False,
                    data=None,
                    source="alpha_vantage",
                    error_message=f"RSI data not found in response. Keys: {list(data.keys())}",
                )

            rsi_data = data[ta_key]
            records = []
            for dt_str, values in rsi_data.items():
                records.append({
                    "timestamp": pd.to_datetime(dt_str),
                    "rsi": float(values.get("RSI", 0)),
                })

            df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)

            return FetchResult(
                success=True,
                data=df,
                source="alpha_vantage",
                rows_fetched=len(df),
            )

        except requests.exceptions.RequestException as e:
            return FetchResult(
                success=False,
                data=None,
                source="alpha_vantage",
                error_message=f"Request failed: {str(e)}",
            )
        except Exception as e:
            return FetchResult(
                success=False,
                data=None,
                source="alpha_vantage",
                error_message=f"Parse error: {str(e)}",
            )

    def fetch_alpha_vantage_macd(
        self,
        symbol: str,
        interval: str = "daily",
        fastperiod: int = 12,
        slowperiod: int = 26,
        signalperiod: int = 9,
        series_type: str = "close",
    ) -> FetchResult:
        """Fetch MACD technical indicator from Alpha Vantage."""
        alpha_vantage_limiter.wait()

        params = {
            "function": "MACD",
            "symbol": symbol,
            "interval": interval,
            "fastperiod": fastperiod,
            "slowperiod": slowperiod,
            "signalperiod": signalperiod,
            "series_type": series_type,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }

        try:
            LOGGER.info(f"Fetching MACD from Alpha Vantage for {symbol}")
            response = self.session.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "Error Message" in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message=data["Error Message"],
                )

            if "Note" in data and "API call frequency" in data["Note"]:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message=f"Rate limited: {data['Note']}",
                )

            ta_key = "Technical Analysis: MACD"
            if ta_key not in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message="MACD data not found in response",
                )

            macd_data = data[ta_key]
            records = []
            for dt_str, values in macd_data.items():
                records.append({
                    "timestamp": pd.to_datetime(dt_str),
                    "macd": float(values.get("MACD", 0)),
                    "macd_signal": float(values.get("MACD_Signal", 0)),
                    "macd_hist": float(values.get("MACD_Hist", 0)),
                })

            df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)

            return FetchResult(
                success=True, data=df, source="alpha_vantage", rows_fetched=len(df),
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="alpha_vantage",
                error_message=f"Error: {str(e)}",
            )

    def fetch_alpha_vantage_fx_rate(
        self,
        from_currency: str = "USD",
        to_currency: str = "EGP",
    ) -> FetchResult:
        """
        Fetch current FX rate from Alpha Vantage.

        Returns:
            FetchResult with current exchange rate
        """
        alpha_vantage_limiter.wait()

        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }

        try:
            LOGGER.info(f"Fetching FX rate from Alpha Vantage: {from_currency}/{to_currency}")
            response = self.session.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "Error Message" in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message=data["Error Message"],
                )

            if "Note" in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message=f"Rate limited: {data['Note']}",
                )

            rate_key = "Realtime Currency Exchange Rate"
            if rate_key not in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message="Exchange rate data not found",
                )

            rate_data = data[rate_key]
            df = pd.DataFrame([{
                "from_currency": rate_data.get("1. From_Currency Code"),
                "to_currency": rate_data.get("3. To_Currency Code"),
                "rate": float(rate_data.get("5. Exchange Rate", 0)),
                "timestamp": rate_data.get("6. Last Refreshed"),
            }])

            return FetchResult(
                success=True, data=df, source="alpha_vantage", rows_fetched=1,
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="alpha_vantage",
                error_message=f"Error: {str(e)}",
            )

    def fetch_alpha_vantage_fx_daily(
        self,
        from_currency: str = "USD",
        to_currency: str = "EGP",
    ) -> FetchResult:
        """Fetch daily FX time series from Alpha Vantage."""
        alpha_vantage_limiter.wait()

        params = {
            "function": "FX_DAILY",
            "from_symbol": from_currency,
            "to_symbol": to_currency,
            "apikey": ALPHA_VANTAGE_API_KEY,
        }

        try:
            LOGGER.info(f"Fetching daily FX from Alpha Vantage: {from_currency}/{to_currency}")
            response = self.session.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "Error Message" in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message=data["Error Message"],
                )

            if "Note" in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message=f"Rate limited: {data['Note']}",
                )

            ts_key = "Time Series FX (Daily)"
            if ts_key not in data:
                return FetchResult(
                    success=False, data=None, source="alpha_vantage",
                    error_message="FX daily data not found",
                )

            fx_data = data[ts_key]
            records = []
            for date_str, values in fx_data.items():
                records.append({
                    "trade_date": pd.to_datetime(date_str),
                    "open": float(values.get("1. open", 0)),
                    "high": float(values.get("2. high", 0)),
                    "low": float(values.get("3. low", 0)),
                    "close": float(values.get("4. close", 0)),
                })

            df = pd.DataFrame(records).sort_values("trade_date").reset_index(drop=True)

            return FetchResult(
                success=True, data=df, source="alpha_vantage", rows_fetched=len(df),
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="alpha_vantage",
                error_message=f"Error: {str(e)}",
            )

    # ==================== FMP Methods ====================

    def fetch_fmp_quote(self, symbol: str) -> FetchResult:
        """
        Fetch latest quote from Financial Modeling Prep.

        Args:
            symbol: Stock/commodity symbol (e.g., "BZ=F" for Brent)

        Returns:
            FetchResult with quote data
        """
        fmp_limiter.wait()

        url = f"{FMP_BASE_URL}/quote/{symbol}"
        params = {"apikey": FMP_API_KEY}

        try:
            LOGGER.info(f"Fetching quote from FMP for {symbol}")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list):
                return FetchResult(
                    success=False, data=None, source="fmp",
                    error_message="Empty or invalid response from FMP",
                )

            quote = data[0]
            df = pd.DataFrame([{
                "symbol": quote.get("symbol"),
                "price": quote.get("price"),
                "change": quote.get("change"),
                "change_percent": quote.get("changesPercentage"),
                "timestamp": datetime.now(),
            }])

            return FetchResult(
                success=True, data=df, source="fmp", rows_fetched=1,
            )

        except requests.exceptions.RequestException as e:
            return FetchResult(
                success=False, data=None, source="fmp",
                error_message=f"Request failed: {str(e)}",
            )
        except Exception as e:
            return FetchResult(
                success=False, data=None, source="fmp",
                error_message=f"Error: {str(e)}",
            )

    def fetch_fmp_historical(
        self,
        symbol: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FetchResult:
        """
        Fetch historical price data from FMP.

        Args:
            symbol: Stock/commodity symbol
            from_date: Start date (default: 30 days ago)
            to_date: End date (default: today)

        Returns:
            FetchResult with historical OHLCV data
        """
        fmp_limiter.wait()

        if to_date is None:
            to_date = date.today()
        if from_date is None:
            from_date = to_date - timedelta(days=30)

        url = f"{FMP_BASE_URL}/historical-price-full/{symbol}"
        params = {
            "apikey": FMP_API_KEY,
            "from": from_date.strftime("%Y-%m-%d"),
            "to": to_date.strftime("%Y-%m-%d"),
        }

        try:
            LOGGER.info(f"Fetching historical from FMP for {symbol} ({from_date} to {to_date})")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or "historical" not in data:
                return FetchResult(
                    success=False, data=None, source="fmp",
                    error_message="Historical data not found in response",
                )

            historical = data["historical"]
            if not historical:
                return FetchResult(
                    success=False, data=None, source="fmp",
                    error_message="Empty historical data",
                )

            records = []
            for item in historical:
                records.append({
                    "trade_date": pd.to_datetime(item.get("date")),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": int(item.get("volume", 0)),
                })

            df = pd.DataFrame(records).sort_values("trade_date").reset_index(drop=True)

            return FetchResult(
                success=True, data=df, source="fmp", rows_fetched=len(df),
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="fmp",
                error_message=f"Error: {str(e)}",
            )

    def fetch_fmp_commodity_quote(self, commodity: str = "BZ") -> FetchResult:
        """
        Fetch commodity quote from FMP.
        BZ = Brent Crude, CL = WTI Crude
        """
        fmp_limiter.wait()

        url = f"{FMP_BASE_URL}/quote/{commodity}"
        params = {"apikey": FMP_API_KEY}

        try:
            LOGGER.info(f"Fetching commodity quote from FMP for {commodity}")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list) or len(data) == 0:
                return FetchResult(
                    success=False, data=None, source="fmp",
                    error_message="Empty commodity response from FMP",
                )

            quote = data[0]
            df = pd.DataFrame([{
                "symbol": quote.get("symbol"),
                "name": quote.get("name"),
                "price": quote.get("price"),
                "change": quote.get("change"),
                "change_percent": quote.get("changesPercentage"),
                "day_low": quote.get("dayLow"),
                "day_high": quote.get("dayHigh"),
                "year_high": quote.get("yearHigh"),
                "year_low": quote.get("yearLow"),
                "volume": quote.get("volume"),
                "timestamp": datetime.now(),
            }])

            return FetchResult(
                success=True, data=df, source="fmp", rows_fetched=1,
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="fmp",
                error_message=f"Error: {str(e)}",
            )

    # ==================== EODHD Methods ====================

    def fetch_eodhd_historical(
        self,
        symbol: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FetchResult:
        """
        Fetch historical price data from EODHD.

        Args:
            symbol: EODHD ticker symbol (e.g., "CBKD.LSE" for CIB Egypt, "BNO" for Brent)
            from_date: Start date (default: 30 days ago)
            to_date: End date (default: today)

        Returns:
            FetchResult with historical OHLCV data
        """
        eodhd_limiter.wait()

        if to_date is None:
            to_date = date.today()
        if from_date is None:
            from_date = to_date - timedelta(days=30)

        url = f"{EODHD_BASE_URL}/eod/{symbol}"
        params = {
            "api_token": EODHD_API_KEY,
            "fmt": "json",
            "from": from_date.strftime("%Y-%m-%d"),
            "to": to_date.strftime("%Y-%m-%d"),
        }

        try:
            LOGGER.info(f"Fetching historical from EODHD for {symbol} ({from_date} to {to_date})")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list) or len(data) == 0:
                return FetchResult(
                    success=False, data=None, source="eodhd",
                    error_message="Empty or invalid response from EODHD",
                )

            records = []
            for item in data:
                records.append({
                    "trade_date": pd.to_datetime(item.get("date")),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": int(item.get("volume", 0)),
                    "adjusted_close": float(item.get("adjusted_close", 0)),
                })

            df = pd.DataFrame(records).sort_values("trade_date").reset_index(drop=True)

            return FetchResult(
                success=True, data=df, source="eodhd", rows_fetched=len(df),
            )

        except requests.exceptions.RequestException as e:
            return FetchResult(
                success=False, data=None, source="eodhd",
                error_message=f"Request failed: {str(e)}",
            )
        except Exception as e:
            return FetchResult(
                success=False, data=None, source="eodhd",
                error_message=f"Error: {str(e)}",
            )

    def fetch_eodhd_egx_stock(
        self,
        symbol: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FetchResult:
        """
        Fetch EGX stock data from EODHD using GDR listings.

        Maps internal symbols to EODHD ticker formats:
        - COMI.CA -> CBKD.LSE (CIB Egypt GDR on LSE)
        - CIBEY -> CIBEY (CIB Egypt OTC)

        IMPORTANT: .LSE tickers return USD prices (GDRs). These are converted
        to EGP using the current USD/EGP exchange rate to match local EGX prices.

        Args:
            symbol: Internal EGX symbol (e.g., "COMI.CA", "COMI")
            from_date: Start date
            to_date: End date

        Returns:
            FetchResult with OHLCV data in EGP currency
        """
        # Map internal EGX symbols to EODHD tickers
        egx_to_eodhd = {
            "COMI": "CBKD.LSE",      # Commercial International Bank Egypt GDR
            "COMI.CA": "CBKD.LSE",   # Same GDR, different internal naming
            "CIBEY": "CIBEY",        # CIB Egypt OTC
            "CBKD": "CBKD.LSE",      # Direct mapping to GDR
        }

        # Default: try the symbol as-is with .LSE suffix if it looks like an EGX stock
        eodhd_symbol = egx_to_eodhd.get(symbol.upper(), None)

        if eodhd_symbol is None:
            # If not in mapping, assume it's already an EODHD ticker
            eodhd_symbol = symbol

        LOGGER.info(f"Mapped EGX symbol {symbol} to EODHD ticker {eodhd_symbol}")

        # Fetch data from EODHD
        result = self.fetch_eodhd_historical(eodhd_symbol, from_date, to_date)

        # If it's a London Stock Exchange GDR (.LSE suffix), convert USD to EGP
        if result.success and result.data is not None and eodhd_symbol.endswith(".LSE"):
            LOGGER.info(f"Converting {eodhd_symbol} prices from USD to EGP")

            # Fetch current USD/EGP exchange rate
            fx_result = self.fetch_alpha_vantage_fx_rate("USD", "EGP")

            if fx_result.success and fx_result.data is not None:
                usd_egp_rate = float(fx_result.data.iloc[0]["rate"])
                LOGGER.info(f"USD/EGP exchange rate: {usd_egp_rate}")

                # Convert OHLC prices from USD to EGP
                price_columns = ["open", "high", "low", "close", "adjusted_close"]
                for col in price_columns:
                    if col in result.data.columns:
                        result.data[col] = result.data[col] * usd_egp_rate

                LOGGER.info(f"Prices converted to EGP using rate {usd_egp_rate}")
            else:
                LOGGER.warning(f"Failed to get USD/EGP rate: {fx_result.error_message}. Returning USD prices.")

        return result

    def fetch_eodhd_brent_crude(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FetchResult:
        """
        Fetch Brent Crude data from EODHD using BNO ETF.

        BNO (United States Brent Oil Fund) tracks Brent Crude futures prices.

        Args:
            from_date: Start date
            to_date: End date

        Returns:
            FetchResult with OHLCV data
        """
        LOGGER.info("Fetching Brent Crude from EODHD via BNO ETF")
        return self.fetch_eodhd_historical("BNO", from_date, to_date)

    # ==================== Investing.com Methods ====================

    def fetch_investing_egx_stock(
        self,
        symbol: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FetchResult:
        """
        Fetch EGX stock data from Investing.com using investpy.

        Args:
            symbol: EGX symbol (e.g., "COMI")
            from_date: Start date
            to_date: End date

        Returns:
            FetchResult with OHLCV data
        """
        investing_limiter.wait()

        if to_date is None:
            to_date = date.today()
        if from_date is None:
            from_date = to_date - timedelta(days=30)

        try:
            LOGGER.info(f"Fetching EGX stock from Investing.com: {symbol}")

            # Try to import investpy
            try:
                import investpy
            except ImportError:
                return FetchResult(
                    success=False, data=None, source="investing_com",
                    error_message="investpy not installed",
                )

            # Search for the stock
            search_results = investpy.search_quotes(text=symbol, products=["stocks"], countries=["egypt"], n_results=1)

            if not search_results:
                return FetchResult(
                    success=False, data=None, source="investing_com",
                    error_message=f"Stock {symbol} not found on Investing.com",
                )

            stock = search_results[0]

            # Fetch historical data
            df = stock.retrieve_historical_data(from_date=from_date.strftime("%d/%m/%Y"), to_date=to_date.strftime("%d/%m/%Y"))

            if df is None or df.empty:
                return FetchResult(
                    success=False, data=None, source="investing_com",
                    error_message="No historical data returned",
                )

            # Rename columns to standard format
            df = df.reset_index()
            df = df.rename(columns={
                "Date": "trade_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })

            return FetchResult(
                success=True, data=df, source="investing_com", rows_fetched=len(df),
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="investing_com",
                error_message=f"Error: {str(e)}",
            )

    def fetch_investing_commodity(
        self,
        commodity: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FetchResult:
        """
        Fetch commodity data from Investing.com.

        Args:
            commodity: Commodity name (e.g., "Brent Oil", "Urea")
            from_date: Start date
            to_date: End date

        Returns:
            FetchResult with OHLCV data
        """
        investing_limiter.wait()

        if to_date is None:
            to_date = date.today()
        if from_date is None:
            from_date = to_date - timedelta(days=30)

        try:
            LOGGER.info(f"Fetching commodity from Investing.com: {commodity}")

            try:
                import investpy
            except ImportError:
                return FetchResult(
                    success=False, data=None, source="investing_com",
                    error_message="investpy not installed",
                )

            # Map common names to investpy names
            commodity_map = {
                "brent": "Brent Oil",
                "brent crude": "Brent Oil",
                "bz": "Brent Oil",
                "urea": "Urea",
            }

            search_term = commodity_map.get(commodity.lower(), commodity)

            # Search for the commodity
            search_results = investpy.search_quotes(text=search_term, products=["commodities"], n_results=1)

            if not search_results:
                return FetchResult(
                    success=False, data=None, source="investing_com",
                    error_message=f"Commodity {commodity} not found on Investing.com",
                )

            comm = search_results[0]
            df = comm.retrieve_historical_data(from_date=from_date.strftime("%d/%m/%Y"), to_date=to_date.strftime("%d/%m/%Y"))

            if df is None or df.empty:
                return FetchResult(
                    success=False, data=None, source="investing_com",
                    error_message="No historical data returned",
                )

            df = df.reset_index()
            df = df.rename(columns={
                "Date": "trade_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })

            return FetchResult(
                success=True, data=df, source="investing_com", rows_fetched=len(df),
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="investing_com",
                error_message=f"Error: {str(e)}",
            )

    # ==================== Fallback Chain Methods ====================

    def fetch_with_fallback(
        self,
        data_type: str,
        fetchers: list[Callable[[], FetchResult]],
    ) -> FetchResult:
        """
        Execute fetchers in order until one succeeds.

        Args:
            data_type: Type of data being fetched (for logging)
            fetchers: List of fetcher functions to try in order

        Returns:
            First successful FetchResult or last failure
        """
        last_error = None

        for i, fetcher in enumerate(fetchers):
            result = fetcher()
            if result.success:
                LOGGER.info(f"Successfully fetched {data_type} from {result.source}")
                return result
            else:
                LOGGER.warning(f"Fetcher {i+1} failed for {data_type}: {result.error_message}")
                last_error = result

        LOGGER.error(f"All fetchers failed for {data_type}")
        return last_error or FetchResult(
            success=False, data=None, source="none",
            error_message="All data sources failed",
        )

    def fetch_egx_stock(self, symbol: str, days: int = 30) -> FetchResult:
        """
        Fetch EGX stock with fallback chain.
        Primary: TradingView (direct EGX exchange data)
        Fallback: EODHD (GDR listings), Investing.com, yfinance
        """
        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        return self.fetch_with_fallback(
            f"EGX stock {symbol}",
            [
                lambda: self._fetch_tradingview_egx(symbol, from_date, to_date),
                lambda: self.fetch_eodhd_egx_stock(symbol, from_date, to_date),
                lambda: self.fetch_investing_egx_stock(symbol, from_date, to_date),
                lambda: self._fetch_yfinance_egx(symbol, from_date, to_date),
            ],
        )

    def _fetch_tradingview_brent(self, from_date: date, to_date: date) -> FetchResult:
        """Fetch Brent Crude from TradingView (ICE exchange)."""
        try:
            tradingview_limiter.wait()
            tv = self._get_tv_client()
            df = tv.get_hist(symbol="BZ1!", exchange="ICE", interval=Interval.in_daily, n_bars=5000)
            if df is None or df.empty:
                return FetchResult(success=False, data=None, source="tradingview",
                                   error_message="No TradingView Brent data")
            if "symbol" in df.columns:
                df = df.drop(columns=["symbol"])
            if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df = df.sort_index()
            if from_date:
                df = df.loc[df.index >= pd.Timestamp(from_date)]
            if to_date:
                df = df.loc[df.index <= pd.Timestamp(to_date)]
            df = df.reset_index()
            df = df.rename(columns={df.columns[0]: "trade_date"})
            return FetchResult(success=True, data=df, source="tradingview", rows_fetched=len(df))
        except Exception as e:
            return FetchResult(success=False, data=None, source="tradingview",
                               error_message=f"TradingView Brent error: {e}")

    def fetch_brent_crude(self, days: int = 30) -> FetchResult:
        """
        Fetch Brent Crude with fallback chain.
        Primary: TradingView (ICE exchange)
        Fallback: EODHD (BNO ETF), FMP, yfinance, Investing.com
        """
        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        return self.fetch_with_fallback(
            "Brent Crude",
            [
                lambda: self._fetch_tradingview_brent(from_date, to_date),
                lambda: self.fetch_eodhd_brent_crude(from_date, to_date),
                lambda: self.fetch_fmp_historical("BZ=F", from_date, to_date),
                lambda: self._fetch_yfinance("BZ=F", from_date, to_date),
                lambda: self.fetch_investing_commodity("Brent", from_date, to_date),
            ],
        )

    def fetch_urea(self, days: int = 30) -> FetchResult:
        """Fetch Urea prices with fallback chain."""
        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        return self.fetch_with_fallback(
            "Urea",
            [
                lambda: self.fetch_investing_commodity("Urea", from_date, to_date),
                lambda: self._fetch_yfinance_urea(from_date, to_date),
            ],
        )

    def _fetch_tradingview_usd_egp(self, from_date: date, to_date: date) -> FetchResult:
        """Fetch USD/EGP from TradingView."""
        try:
            tradingview_limiter.wait()
            tv = self._get_tv_client()
            df = tv.get_hist(symbol="USDEGP", exchange="FX", interval=Interval.in_daily, n_bars=5000)
            if df is None or df.empty:
                return FetchResult(success=False, data=None, source="tradingview",
                                   error_message="No TradingView USD/EGP data")
            if "symbol" in df.columns:
                df = df.drop(columns=["symbol"])
            if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df = df.sort_index()
            if from_date:
                df = df.loc[df.index >= pd.Timestamp(from_date)]
            if to_date:
                df = df.loc[df.index <= pd.Timestamp(to_date)]
            df = df.reset_index()
            df = df.rename(columns={df.columns[0]: "trade_date"})
            return FetchResult(success=True, data=df, source="tradingview", rows_fetched=len(df))
        except Exception as e:
            return FetchResult(success=False, data=None, source="tradingview",
                               error_message=f"TradingView USD/EGP error: {e}")

    def fetch_usd_egp(self, days: int = 30) -> FetchResult:
        """Fetch USD/EGP rates with fallback chain.
        Primary: TradingView, Fallback: Alpha Vantage, yfinance
        """
        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        return self.fetch_with_fallback(
            "USD/EGP",
            [
                lambda: self._fetch_tradingview_usd_egp(from_date, to_date),
                lambda: self.fetch_alpha_vantage_fx_daily("USD", "EGP"),
                lambda: self._fetch_yfinance("EGP=X", from_date, to_date),
            ],
        )

    def fetch_sp500(self, days: int = 30) -> FetchResult:
        """Fetch S&P 500 data with fallback chain."""
        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        return self.fetch_with_fallback(
            "S&P 500",
            [
                lambda: self.fetch_fmp_historical("SPY", from_date, to_date),
                lambda: self._fetch_yfinance("SPY", from_date, to_date),
            ],
        )

    def fetch_rsi(self, symbol: str) -> FetchResult:
        """Fetch RSI with fallback chain."""
        return self.fetch_with_fallback(
            f"RSI for {symbol}",
            [
                lambda: self.fetch_alpha_vantage_rsi(symbol),
            ],
        )

    # ==================== yfinance Fallback Methods ====================

    def _fetch_yfinance(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> FetchResult:
        """Fallback fetcher using yfinance."""
        try:
            import yfinance as yf

            LOGGER.info(f"Fetching from yfinance: {symbol}")
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=from_date.isoformat(), end=to_date.isoformat())

            if hist.empty:
                return FetchResult(
                    success=False, data=None, source="yfinance",
                    error_message="No data returned",
                )

            df = hist.reset_index()
            df = df.rename(columns={
                "Date": "trade_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })

            return FetchResult(
                success=True, data=df, source="yfinance", rows_fetched=len(df),
            )

        except Exception as e:
            return FetchResult(
                success=False, data=None, source="yfinance",
                error_message=f"Error: {str(e)}",
            )

    def _fetch_yfinance_egx(self, symbol: str, from_date: date, to_date: date) -> FetchResult:
        """Fetch EGX stock from yfinance with .CA suffix."""
        # EGX stocks typically use .CA suffix on Yahoo Finance
        yf_symbol = f"{symbol}.CA" if not symbol.endswith(".CA") else symbol
        return self._fetch_yfinance(yf_symbol, from_date, to_date)

    def _fetch_yfinance_urea(self, from_date: date, to_date: date) -> FetchResult:
        """Fetch Urea from yfinance using proxy tickers."""
        # Try various fertilizer proxies
        for ticker in ["Urea=F", "FERT=F", "CF"]:
            result = self._fetch_yfinance(ticker, from_date, to_date)
            if result.success:
                # Rename to Urea for consistency
                if result.data is not None:
                    result.data["commodity_name"] = "Urea"
                return result
        return FetchResult(
            success=False, data=None, source="yfinance",
            error_message="No urea proxy data available",
        )


def create_fetcher() -> DataFetcher:
    """Factory function to create a DataFetcher instance."""
    return DataFetcher()
