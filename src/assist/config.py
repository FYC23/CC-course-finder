from __future__ import annotations

from pathlib import Path


ASSIST_BASE_URL = "https://assist.org"
USER_AGENT = "cc-course-finder/0.1 (+https://assist.org)"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ARTIFACT_DIR = DATA_DIR / "assist_artifacts"
DB_PATH = DATA_DIR / "assist.sqlite3"

