from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _project_path(name: str, default_name: str) -> Path:
    configured = Path(os.getenv(name, default_name))
    return configured.resolve() if configured.is_absolute() else (BASE_DIR / configured).resolve()


LOCAL_DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(BASE_DIR))) / "stock_look_back"
DATABASE_PATH = _project_path("DATABASE_PATH", str(LOCAL_DATA_DIR / "quant_backtest.db"))
DATA_CACHE_DIR = _project_path("DATA_CACHE_DIR", str(LOCAL_DATA_DIR / "data_cache"))
CORS_ORIGINS = [v.strip() for v in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", "0"))
TRADING_DAYS_PER_YEAR = 245
