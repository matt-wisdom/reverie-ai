import os
import sys
from unittest.mock import MagicMock, patch

os.environ["GOOGLE_API_KEY"] = "fake_key"
os.environ["GEMINI_API_KEY"] = "fake_key"
sys.modules["chromadb"] = MagicMock()
sys.modules["chromadb.utils"] = MagicMock()
sys.modules["chromadb.utils.embedding_functions"] = MagicMock()
sys.modules["ladybug"] = MagicMock()

import pytest
from app.graph.workflow import app_graph

@pytest.mark.asyncio
async def test_workflow_execution():
    initial_state = {
        "messages": [],
        "code": "def hello(): print('world')",
        "review_results": [],
        "vulnerability_results": [],
        "test_results": [],
        "final_report": "",
        "current_task": ""
    }
    
    with patch("app.agents.kg_builder.KGBuilder.build_from_code") as mock_kg, \
         patch("app.agents.reviewer.ReviewerAgent.run") as mock_rev, \
         patch("app.agents.scanner.ScannerAgent.run") as mock_scan, \
         patch("app.agents.test_gen.TestGenAgent.run") as mock_test, \
         patch("app.agents.reporter.ReporterAgent.run") as mock_rep:
        
        mock_kg.return_value = "KG Done"
        mock_rev.return_value = {"review_results": ["Good"]}
        mock_scan.return_value = {"vulnerability_results": ["Clean"]}
        mock_test.return_value = {"test_results": ["Tests Done"]}
        mock_rep.return_value = {"final_report": "All good"}
        
        final_state = await app_graph.ainvoke(initial_state)
        
        assert final_state["final_report"] == "All good"
