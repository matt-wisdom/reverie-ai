import os
from aiolimiter import AsyncLimiter

# Gemini Settings
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_TYPE = os.getenv("GEMINI_MODEL_TYPE", "gemini-1.5-flash")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/embedding-001")

# Rate Limit: defaults to 15 requests per minute (free tier safety)
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "15"))
gemini_limiter = AsyncLimiter(GEMINI_RPM, 60)
