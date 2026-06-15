import os
import sys
from unittest.mock import MagicMock

# Mock environment variables
os.environ["GOOGLE_API_KEY"] = "fake_key"
os.environ["GEMINI_API_KEY"] = "fake_key"

# Mock packages
chroma_mock = MagicMock()
sys.modules["chromadb"] = chroma_mock
sys.modules["chromadb.api"] = MagicMock()
sys.modules["chromadb.api.types"] = MagicMock()
sys.modules["ladybug"] = MagicMock()
