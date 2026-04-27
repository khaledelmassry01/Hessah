from datetime import date
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path("services/ai-engine").resolve()))
os.environ["AI_MODEL_DIR"] = str(Path("infra/models_data").resolve())
os.environ["DB_HOST"] = "127.0.0.1"
os.environ["DB_PORT"] = "3307"
os.environ["DB_USER"] = "egx_app_user"
os.environ["DB_PASSWORD"] = "EGX_App_7wN!9Qx2#M4Lz8"
os.environ["DB_NAME"] = "egx_portfolio"

from app.model_training import train_xgboost_models

symbols = ["ABUK.CA", "ALCN.CA", "AMOC.CA", "AUTO.CA", "BTFH.CA"]

result = train_xgboost_models(
    model_dir=Path("infra/models_data"),
    target_mode="RETURN_PCT",
    symbols=symbols,
    horizon_days=5,
    min_rows_per_symbol=80,
    train_start=date(2021, 1, 1),
    train_end=date(2024, 12, 31),
    validation_start=date(2025, 1, 1),
    validation_end=date(2026, 4, 20),
    use_recency_weighting=False,
    n_estimators=100,
    learning_rate=0.1,
)

print(result)
