from datetime import date
from pathlib import Path
import os
import sys
import time

sys.path.insert(0, str(Path("services/ai-engine").resolve()))
os.environ["DB_HOST"] = "127.0.0.1"
os.environ["DB_PORT"] = "3307"
os.environ["DB_USER"] = "egx_app_user"
os.environ["DB_PASSWORD"] = "EGX_App_7wN!9Qx2#M4Lz8"
os.environ["DB_NAME"] = "egx_portfolio"

from app.feature_engineering import load_historical_market_data, load_market_context_data, resolve_mysql_settings

settings = resolve_mysql_settings()
print("settings:", settings)

start = time.time()
raw = load_historical_market_data(
    symbols=["ABUK.CA", "ALCN.CA"],
    start_date=date(2025, 1, 1),
    end_date=date(2026, 4, 20),
)
print("historical rows:", len(raw), "secs:", round(time.time() - start, 2))

start = time.time()
ctx = load_market_context_data(
    start_date=date(2025, 1, 1),
    end_date=date(2026, 4, 20),
)
print("context rows:", len(ctx), "secs:", round(time.time() - start, 2))
print("context cols:", list(ctx.columns))
if not ctx.empty:
    print(ctx.tail(2).to_string(index=False))
