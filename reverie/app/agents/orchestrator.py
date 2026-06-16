import os
import re
from typing import List, Dict
from langgraph.types import Send
from ..graph.state import AgentState
from ..core.logging_config import get_logger

logger = get_logger(__name__)

# High risk patterns
HIGH_RISK_PATTERNS = [
    r"auth",
    r"login",
    r"permission",
    r"payment",
    r"crypto",
    r"admin",
    r"session",
    r"password",
    r"security",
    r"route",
    r"api",
    r"endpoint",
    r"controller",
    r"view",
    r"handler",
]


class Orchestrator:
    @staticmethod
    async def plan(state: AgentState):
        """Orchestrator node: decides the execution plan."""
        tag = state["project_tag"]
        logger.info(f"Orchestrator planning for project: {tag}")

        files = state.get("files_to_review", [])
        if not files:
            logger.warning("No files to review.")
            return {"next_action": "end"}

        # 1. Fetch Codebase Summary from Project Node (Stored during ingestion)
        codebase_summary = state.get("codebase_summary")
        if not codebase_summary:
            try:
                from ..db.ladybug_db import LadybugClient
                from ..core.config import get_project_dir
                project_dir = get_project_dir(tag)
                client = LadybugClient(db_path=project_dir / "graph_db")

                # Check for stored summary first
                res = client.execute(
                    "MATCH (p:Project {id: $id}) RETURN p.summary, p.name", {"id": tag}
                )
                if res.has_next():
                    df = res.get_as_df()
                    codebase_summary = df.iloc[0]["p.summary"]
                    project_name = df.iloc[0]["p.name"]
                # Fallback: compute and store if missing
                if not codebase_summary:
                    logger.info(
                        "GRAPH: Summary missing in Project node. Regenerating fallback..."
                    )
                    from .ingestion import IngestionPipeline

                    pipeline = IngestionPipeline(tag=tag)
                    await pipeline._generate_and_store_project_summary(
                        project_name or tag
                    )

                    # Re-fetch
                    res = client.execute(
                        "MATCH (p:Project {id: $id}) RETURN p.summary", {"id": tag}
                    )
                    if res.has_next():
                        codebase_summary = res.get_as_df().iloc[0]["p.summary"]

            except Exception as e:
                logger.warning(f"Failed to fetch/generate codebase summary: {e}")
                codebase_summary = "Architectural overview unavailable."

        # 2. Prioritization
        prioritized_files = Orchestrator._prioritize_files(files)

        # 3. Batching & Agent Selection
        return {
            "files_to_review": prioritized_files,
            "next_action": "fan_out",
            "codebase_summary": codebase_summary,
        }

    @staticmethod
    def _prioritize_files(files: List[Dict]) -> List[Dict]:
        """Scores and sorts files based on risk and history."""
        for f in files:
            score = 0
            path = f["path"].lower()

            # Pattern matching for high risk
            if any(re.search(pattern, path) for pattern in HIGH_RISK_PATTERNS):
                score += 5

            # New files (simulated here, real would check LadybugDB history)
            # if is_new(path): score += 3

            f["priority"] = score

            # Agent Selection Logic
            f["assigned_agents"] = Orchestrator._assign_agents(f)

        return sorted(files, key=lambda x: x["priority"], reverse=True)

    @staticmethod
    def _assign_agents(file: Dict) -> List[str]:
        path = file["path"].lower()
        ext = path.split(".")[-1]

        # Skip docs
        if ext in ["md", "txt", "pdf"]:
            return []

        agents = ["security"]  # Security agent runs on almost everything code-related

        # Skip smells and tests for configs/migrations
        if any(x in path for x in ["config", "migration", "generated"]):
            return agents

        # Add Bug and Smell agents for core logic
        agents.extend(["bug_detector", "smell_detector"])

        # Add Test Writer if not a test file already
        if "test" not in path:
            agents.append("test_writer")

        return agents


def get_fan_out_commands(state: AgentState):
    """
    Conditional edge function that returns a list of Send objects
    to parallelize agent execution across batches of files.
    """
    commands = []
    files = state["files_to_review"]
    batch_size = 5  # Configurable batch size

    # Simple target mapping for now
    agent_nodes = {
        "security": "security_agent",
        "bug_detector": "bug_detector_agent",
        "smell_detector": "smell_detector_agent",
        "test_writer": "test_writer_agent",
    }

    common_payload = {
        "project_tag": state["project_tag"],
        "project_root": state.get("project_root", ""),
        "project_config": state.get("project_config", {}),
        "user_prompt": state.get("user_prompt"),
        "codebase_summary": state.get("codebase_summary"),
    }

    # If mode is subset, only run the target agents
    if state["review_mode"] == "subset" and state.get("target_agents"):
        for target in state["target_agents"]:
            for i in range(0, len(files), batch_size):
                batch = files[i : i + batch_size]
                payload = {**common_payload, "files": batch}
                commands.append(Send(agent_nodes[target], payload))
        return commands

    # For full/diff, fan out per agent per batch
    for agent_key, node_name in agent_nodes.items():
        # Only send files assigned to this specific agent
        assigned_files = [f for f in files if agent_key in f["assigned_agents"]]

        # Skip smell agent in diff mode
        if state["review_mode"] == "diff" and agent_key == "smell_detector":
            continue

        for i in range(0, len(assigned_files), batch_size):
            batch = assigned_files[i : i + batch_size]
            payload = {**common_payload, "files": batch}
            commands.append(Send(node_name, payload))

    return commands
