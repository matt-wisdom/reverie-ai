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
    # Security-specific fields
    rule_id: Optional[str]
    owasp_category: Optional[str]
    cwe_id: Optional[str]
    remediation: Optional[str]
    confidence: Optional[str]  # low, medium, high


class FileToReview(TypedDict):
    path: str
    content: str
    language: str
    priority: int  # 0-10 (high is better)
    assigned_agents: List[str]


class AgentState(TypedDict):
    project_tag: str
    project_root: str  # Path to the actual source code
    project_config: Dict  # Dynamic configuration from .reverie.yaml
    user_prompt: Optional[str]  # Custom instructions to alter agent behavior
    codebase_summary: Optional[str]  # AI-generated high-level overview

    review_mode: Literal["full", "diff", "subset"]
    target_agents: Optional[List[str]]  # for mode="subset"

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
