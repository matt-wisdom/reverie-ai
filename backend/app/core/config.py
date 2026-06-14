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


# LLM Settings
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" or "deepseek"

# Gemini Settings
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_TYPE = os.getenv("GEMINI_MODEL_TYPE", "gemini-1.5-flash")

# OpenAI / OpenAI-Compatible Settings (DeepSeek, etc.)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Embedding Settings
EMBEDDING_PROVIDER = os.getenv(
    "EMBEDDING_PROVIDER", "gemini"
)  # "gemini" or "huggingface"
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/embedding-001")
HF_EMBEDDING_MODEL = os.getenv(
    "HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)

# Rate Limit: defaults to 15 requests per minute (free tier safety)
LLM_RPM = int(os.getenv("LLM_RPM", os.getenv("GEMINI_RPM", "15")))
llm_limiter = AsyncLimiter(LLM_RPM, 60)
# For backward compatibility
GEMINI_RPM = LLM_RPM
gemini_limiter = llm_limiter

# ReAct Agent Settings
REVERIE_MAX_ITERATIONS = int(os.getenv("REVERIE_MAX_ITERATIONS", "25"))
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
