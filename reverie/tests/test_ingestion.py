import pytest
import os
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def ingestion_pipeline():
    # Use a side effect to ensure the module is fully loaded before constructor is called
    with (
        patch("app.agents.ingestion.ChromaClient"),
        patch("app.agents.ingestion.LadybugClient"),
    ):
        from app.agents.ingestion import IngestionPipeline

        return IngestionPipeline(tag="test-tag")


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
async def test_generate_folder_summary(ingestion_pipeline):
    mock_response = MagicMock()
    mock_response.text = "This is a summary"

    import app.agents.ingestion as ingestion_mod

    # Ensure model exists
    if not hasattr(ingestion_mod, "model"):
        ingestion_mod.model = MagicMock()

    with patch.object(
        ingestion_mod.model, "generate_content_async", new_callable=AsyncMock
    ) as mock_gen:
        mock_gen.return_value = mock_response
        summary = await ingestion_pipeline._generate_folder_summary(
            "/path", ["a.py"], "context"
        )
        assert summary == "This is a summary"


@pytest.mark.asyncio
async def test_process_file_python(ingestion_pipeline, tmp_path):
    code = "class MyClass:\n    def my_func(): pass"
    f = tmp_path / "test.py"
    f.write_text(code)

    ingestion_pipeline.ladybug_client = MagicMock()
    ingestion_pipeline.chroma_client = MagicMock()

    await ingestion_pipeline._process_file(str(f), "py")

    assert ingestion_pipeline.ladybug_client.execute.called
    assert ingestion_pipeline.chroma_client.add_documents.called
