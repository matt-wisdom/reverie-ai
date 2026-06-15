import os
from aiolimiter import AsyncLimiter
from pathlib import Path
from dotenv import load_dotenv

# --- JIT ENVIRONMENT LOADING ---
_ENV_LOADED = False

def _ensure_env():
    global _ENV_LOADED
    if not _ENV_LOADED:
        _local_env = Path(".reverie") / ".env"
        _global_env = Path.home() / ".reverie" / ".env"
        _std_env = Path(".env")
        
        loaded_from = "None"
        if _local_env.exists():
            load_dotenv(dotenv_path=_local_env, override=True)
            loaded_from = str(_local_env)
        elif _global_env.exists():
            load_dotenv(dotenv_path=_global_env, override=True)
            loaded_from = str(_global_env)
        elif _std_env.exists():
            load_dotenv(dotenv_path=_std_env, override=True)
            loaded_from = str(_std_env)
        else:
            load_dotenv(override=True)
            loaded_from = "Standard OS Environment"
        
        # LOUD DEBUGGING
        provider = os.getenv("LLM_PROVIDER", "gemini (default)")
        print(f"--- REVERIE STARTUP (v0.1.2) ---")
        print(f"DEBUG: Config loaded from: {loaded_from}")
        print(f"DEBUG: LLM_PROVIDER set to: {provider}")
        if provider == "openai":
            key = os.getenv("OPENAI_API_KEY")
            print(f"DEBUG: OPENAI_API_KEY found: {'Yes' if key else 'MISSING'}")
        else:
            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            print(f"DEBUG: GEMINI_API_KEY found: {'Yes' if key else 'MISSING'}")
        print(f"---------------------------------")
        
        _ENV_LOADED = True

def _get_env(key: str, default: str = None) -> str:
    _ensure_env()
    return os.getenv(key, default)

# Storage Settings
REVERIE_ROOT = Path(_get_env("REVERIE_STORAGE_PATH", "./.reverie")).absolute()
PROJECTS_ROOT = REVERIE_ROOT / "projects"
GLOBAL_DB_PATH = REVERIE_ROOT / "registry.db"

def get_project_dir(tag: str) -> Path:
    project_dir = PROJECTS_ROOT / tag
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir

# LLM Settings
def get_llm_provider(): return _get_env("LLM_PROVIDER", "gemini")

# Gemini Settings
def get_gemini_api_key(): 
    return _get_env("GOOGLE_API_KEY") or _get_env("GEMINI_API_KEY")
def get_gemini_model(): return _get_env("GEMINI_MODEL_TYPE", "gemini-1.5-flash")

# OpenAI Settings
def get_openai_api_key(): return _get_env("OPENAI_API_KEY")
def get_openai_model(): return _get_env("OPENAI_MODEL_NAME", "gpt-4o")
def get_openai_base_url(): return _get_env("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Embedding Settings
def get_embedding_provider(): return _get_env("EMBEDDING_PROVIDER", "gemini")
GEMINI_EMBEDDING_MODEL = _get_env("GEMINI_EMBEDDING_MODEL", "models/embedding-001")
HF_EMBEDDING_MODEL = _get_env("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Rate Limit
def get_llm_rpm(): return int(_get_env("LLM_RPM", _get_env("GEMINI_RPM", "15")))
llm_limiter = AsyncLimiter(15, 60)

# ReAct Agent Settings
REVERIE_MAX_ITERATIONS = int(_get_env("REVERIE_MAX_ITERATIONS", "25"))
def get_tavily_api_key(): return _get_env("TAVILY_API_KEY")
