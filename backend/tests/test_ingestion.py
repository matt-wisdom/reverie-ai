import os
import sys
from unittest.mock import MagicMock, patch

# Mock environment variables for testing
os.environ["GOOGLE_API_KEY"] = "fake_key"
os.environ["GEMINI_API_KEY"] = "fake_key"

# Proper way to mock packages with submodules
chroma_mock = MagicMock()
sys.modules["chromadb"] = chroma_mock
sys.modules["chromadb.utils"] = MagicMock()
sys.modules["chromadb.utils.embedding_functions"] = MagicMock()
sys.modules["ladybug"] = MagicMock()

import pytest
from app.agents.ingestion import IngestionPipeline

@pytest.fixture
def ingestion_pipeline():
    with patch("app.agents.ingestion.chroma_client"), \
         patch("app.agents.ingestion.ladybug_client"):
        return IngestionPipeline()

@pytest.mark.asyncio
async def test_get_folder_context(ingestion_pipeline, tmp_path):
    d = tmp_path / "sub"
    d.mkdir()
    gemini_file = d / "GEMINI.md"
    gemini_file.write_text("Architecture rules")
    
    context = ingestion_pipeline._get_folder_context(str(d), ["GEMINI.md", "main.py"])
    assert "Architecture rules" in context
    assert "--- GEMINI.md ---" in context

@pytest.mark.asyncio
@patch("app.agents.ingestion.model.generate_content_async")
async def test_generate_folder_summary(mock_gen, ingestion_pipeline):
    mock_response = MagicMock()
    mock_response.text = "This is a summary"
    mock_gen.return_value = mock_response
    
    summary = await ingestion_pipeline._generate_folder_summary("/path", ["a.py"], "context")
    assert summary == "This is a summary"

@pytest.mark.asyncio
async def test_process_file_python(ingestion_pipeline, tmp_path):
    code = "class MyClass:\n    def my_func(): pass"
    f = tmp_path / "test.py"
    f.write_text(code)
    
    with patch("app.agents.ingestion.ladybug_client.execute") as mock_kg, \
         patch("app.agents.ingestion.chroma_client.add_documents") as mock_chroma:
        await ingestion_pipeline._process_file(str(f), "py")
        assert mock_kg.called
        assert mock_chroma.called
