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
from app.data_pipeline import EGX30_CANONICAL_SYMBOLS

result = train_xgboost_models(
    model_dir=Path("infra/models_data"),
    target_mode="RETURN_PCT",
    symbols=EGX30_CANONICAL_SYMBOLS,
    horizon_days=5,
    min_rows_per_symbol=120,
    train_start=date(2019, 1, 1),
    train_end=date(2024, 12, 31),
    validation_start=date(2025, 1, 1),
    validation_end=date(2026, 4, 20),
    n_estimators=120,
    learning_rate=0.05,
)

print(result)
