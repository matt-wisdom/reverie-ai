from langgraph.graph import StateGraph, END
from .state import AgentState
from ..agents.kg_builder import KGBuilder
from ..agents.reviewer import ReviewerAgent
from ..agents.scanner import ScannerAgent
from ..agents.test_gen import TestGenAgent
from ..agents.reporter import ReporterAgent
from ..db.ladybug_db import LadybugClient
from ..core.config import get_project_dir
from ..core.logging_config import get_logger

logger = get_logger(__name__)

def get_clients(state: AgentState):
    tag = state["project_tag"]
    project_dir = get_project_dir(tag)
    ladybug_client = LadybugClient(db_path=project_dir / "graph_db")
    return ladybug_client

# Define the nodes as simple wrappers around the agent classes
def kg_builder_node(state: AgentState):
    logger.info("Starting Knowledge Graph Builder")
    ladybug_client = get_clients(state)
    builder = KGBuilder(ladybug_client)
    result = builder.build_from_code("current_file.py", state["code"])
    return {"current_task": result}

def reviewer_node(state: AgentState):
    logger.info("Starting Reviewer Agent")
    return ReviewerAgent.run(state)

def scanner_node(state: AgentState):
    logger.info("Starting Scanner Agent")
    return ScannerAgent.run(state)

def test_gen_node(state: AgentState):
    logger.info("Starting Test Generator Agent")
    return TestGenAgent.run(state)

def reporter_node(state: AgentState):
    logger.info("Starting Reporter Agent")
    return ReporterAgent.run(state)

# Define the graph
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("kg_builder", kg_builder_node)
workflow.add_node("reviewer", reviewer_node)
workflow.add_node("scanner", scanner_node)
workflow.add_node("test_gen", test_gen_node)
workflow.add_node("reporter", reporter_node)

# Define edges
workflow.set_entry_point("kg_builder")
workflow.add_edge("kg_builder", "reviewer")
workflow.add_edge("reviewer", "scanner")
workflow.add_edge("scanner", "test_gen")
workflow.add_edge("test_gen", "reporter")
workflow.add_edge("reporter", END)

# Compile the graph
app_graph = workflow.compile()
