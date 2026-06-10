import os
from aiolimiter import AsyncLimiter
from pathlib import Path

# Storage Settings
REVERIE_ROOT = Path(os.getenv("REVERIE_STORAGE_PATH", "./.reverie")).absolute()
PROJECTS_ROOT = REVERIE_ROOT / "projects"
GLOBAL_DB_PATH = REVERIE_ROOT / "registry.db"

def get_project_dir(tag: str) -> Path:
    project_dir = PROJECTS_ROOT / tag
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir

# Gemini Settings
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_TYPE = os.getenv("GEMINI_MODEL_TYPE", "gemini-1.5-flash")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/embedding-001")

# Rate Limit: defaults to 15 requests per minute (free tier safety)
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "15"))
gemini_limiter = AsyncLimiter(GEMINI_RPM, 60)
