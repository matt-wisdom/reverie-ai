import os
import sys
from unittest.mock import MagicMock, patch

# Mock environment variables
os.environ["GOOGLE_API_KEY"] = "fake_key"
os.environ["GEMINI_API_KEY"] = "fake_key"

import pytest


@pytest.mark.asyncio
async def test_workflow_execution():
    # Patch the clients where they are used (in the nodes or agents)
    with (
        patch("app.agents.bug_detector.LadybugClient"),
        patch("app.agents.bug_detector.ChromaClient"),
        patch("app.graph.workflow.get_project_dir"),
    ):
        from app.graph.workflow import app_graph

        initial_state = {
            "project_tag": "test-tag",
            "project_config": {"max_iterations": 5},
            "messages": [],
            "code": "def hello(): print('world')",
            "review_mode": "full",
            "target_agents": [],
            "output_dir": None,
            "files_to_review": [
                {
                    "path": "test.py",
                    "content": "print(1)",
                    "language": "py",
                    "priority": 0,
                    "assigned_agents": [
                        "security",
                        "bug_detector",
                        "smell_detector",
                        "test_writer",
                    ],
                }
            ],
            "bug_findings": [],
            "security_findings": [],
            "smell_findings": [],
            "generated_tests": [],
            "next_action": "start",
            "critical_found": False,
            "final_report": "",
        }

        # Patch the nodes directly in workflow.py to test the orchestration
        with (
            patch("app.graph.workflow.BugDetectorAgent") as mock_bug_agent_class,
            patch("app.graph.workflow.security_node") as mock_sec,
            patch("app.graph.workflow.smell_node") as mock_smell,
            patch("app.graph.workflow.test_writer_node") as mock_test,
            patch("app.graph.workflow.ReporterAgent.run") as mock_rep,
        ):
            mock_bug_instance = MagicMock()
            mock_bug_agent_class.return_value = mock_bug_instance
            mock_bug_instance.run = AsyncMock(return_value={"bug_findings": []})

            mock_sec.return_value = {"security_findings": []}
            mock_smell.return_value = {"smell_findings": []}
            mock_test.return_value = {"generated_tests": []}
            mock_rep.return_value = {"final_report": "All good"}

            final_state = await app_graph.ainvoke(initial_state)

            assert "# Review Report for test-tag" in final_state["final_report"]
            assert "Bugs Found" in final_state["final_report"]


from unittest.mock import AsyncMock
