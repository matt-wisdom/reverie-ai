import os
import sys
from unittest.mock import MagicMock, patch

# Mock environment variables
os.environ["GOOGLE_API_KEY"] = "fake_key"
os.environ["GEMINI_API_KEY"] = "fake_key"

import pytest

@pytest.mark.asyncio
async def test_workflow_execution():
    # Explicitly import to ensure attributes exist for patching
    import app.graph.workflow
    
    # Patch the clients where they are used in the workflow
    with patch("app.graph.workflow.LadybugClient"), \
         patch("app.graph.workflow.get_project_dir"):
        
        from app.graph.workflow import app_graph
        
        initial_state = {
            "project_tag": "test-tag",
            "messages": [],
            "code": "def hello(): print('world')",
            "review_results": [],
            "vulnerability_results": [],
            "test_results": [],
            "final_report": "",
            "current_task": ""
        }
        
        with patch("app.graph.workflow.KGBuilder") as mock_kg_class, \
             patch("app.graph.workflow.ReviewerAgent.run") as mock_rev, \
             patch("app.graph.workflow.ScannerAgent.run") as mock_scan, \
             patch("app.graph.workflow.TestGenAgent.run") as mock_test, \
             patch("app.graph.workflow.ReporterAgent.run") as mock_rep:
            
            mock_kg_instance = MagicMock()
            mock_kg_class.return_value = mock_kg_instance
            mock_kg_instance.build_from_code.return_value = "KG Done"
            
            mock_rev.return_value = {"review_results": ["Good"]}
            mock_scan.return_value = {"vulnerability_results": ["Clean"]}
            mock_test.return_value = {"test_results": ["Tests Done"]}
            mock_rep.return_value = {"final_report": "All good"}
            
            final_state = await app_graph.ainvoke(initial_state)
            
            assert final_state["final_report"] == "All good"
