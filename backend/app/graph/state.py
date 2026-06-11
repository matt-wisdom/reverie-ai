from typing import TypedDict, List, Annotated, Literal, Optional, Dict, Sequence
import operator
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class Finding(TypedDict):
    title: str
    category: str  # bug, security, smell
    severity: str  # low, medium, high, critical
    description: str
    file_path: str
    line: int


class FileToReview(TypedDict):
    path: str
    content: str
    language: str
    priority: int  # 0-10 (high is better)
    assigned_agents: List[str]


class AgentState(TypedDict):
    project_tag: str
    project_root: str # Path to the actual source code
    project_config: Dict # Dynamic configuration from .reverie.yaml

    review_mode: Literal["full", "diff", "single"]
    target_agent: Optional[str]  # for mode="single"

    # Message history for ReAct agents
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Files to be processed
    files_to_review: List[FileToReview]

    # Results aggregated via operator.add
    bug_findings: Annotated[List[Finding], operator.add]
    security_findings: Annotated[List[Finding], operator.add]
    smell_findings: Annotated[List[Finding], operator.add]
    generated_tests: Annotated[List[dict], operator.add]

    # Control flow
    next_action: str
    critical_found: bool
    final_report: str
