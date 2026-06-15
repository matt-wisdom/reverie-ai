from typing import List, Dict
from langgraph.graph import StateGraph, END
from langgraph.types import Send
from .state import AgentState, Finding
from ..agents.orchestrator import Orchestrator, get_fan_out_commands
from ..agents.reporter import ReporterAgent
from ..core.config import get_project_dir
from ..core.logging_config import get_logger

logger = get_logger(__name__)

# --- Specialized Agent Wrapper Nodes ---

from ..agents.bug_detector import BugDetectorAgent


async def bug_detector_node(state: Dict):
    """Expects a state with 'files' list and 'project_root' from Send."""
    tag = state.get("project_tag", "default")
    project_root = state.get("project_root", "")
    project_dir = get_project_dir(tag)
    agent = BugDetectorAgent(
        tag=tag, project_dir=str(project_dir), project_root=project_root
    )

    findings = await agent.run(state)
    return findings


from ..agents.security import SecurityAgent


async def security_node(state: Dict):
    """Expects a state with 'files' list and 'project_root' from Send."""
    tag = state.get("project_tag", "default")
    project_root = state.get("project_root", "")
    project_dir = get_project_dir(tag)
    agent = SecurityAgent(
        tag=tag, project_dir=str(project_dir), project_root=project_root
    )

    findings = await agent.run(state)
    return findings


from ..agents.smell_detector import SmellDetectorAgent


async def smell_node(state: Dict):
    """Expects a state with 'files' list and 'project_root' from Send."""
    tag = state.get("project_tag", "default")
    project_root = state.get("project_root", "")
    project_dir = get_project_dir(tag)
    agent = SmellDetectorAgent(
        tag=tag, project_dir=str(project_dir), project_root=project_root
    )

    findings = await agent.run(state)
    return findings


def test_writer_node(state: Dict):
    logger.info(f"Test Writer processing {len(state['files'])} files")
    return {"generated_tests": []}


# --- Main Workflow ---

workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("orchestrator", Orchestrator.plan)
workflow.add_node("bug_detector_agent", bug_detector_node)
workflow.add_node("security_agent", security_node)
workflow.add_node("smell_detector_agent", smell_node)
workflow.add_node("test_writer_agent", test_writer_node)
workflow.add_node("reporter", ReporterAgent.run)

# Define Edges
workflow.set_entry_point("orchestrator")

# The Orchestrator decides where to send work in parallel
workflow.add_conditional_edges(
    "orchestrator",
    get_fan_out_commands,
    [
        "bug_detector_agent",
        "security_agent",
        "smell_detector_agent",
        "test_writer_agent",
    ],
)

# All agents report back to the reporter after parallel completion
# Note: In LangGraph, when multiple 'Send' branches finish,
# they automatically join if they lead to the same node.
workflow.add_edge("bug_detector_agent", "reporter")
workflow.add_edge("security_agent", "reporter")
workflow.add_edge("smell_detector_agent", "reporter")
workflow.add_edge("test_writer_agent", "reporter")

workflow.add_edge("reporter", END)

# Compile
app_graph = workflow.compile()
