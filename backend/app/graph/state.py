from typing import TypedDict, List, Annotated
import operator

class AgentState(TypedDict):
    # Project Info
    project_tag: str
    # The message history
    messages: Annotated[List[dict], operator.add]
    # The code to review
    code: str
    # Results from different agents
    review_results: List[str]
    vulnerability_results: List[str]
    test_results: List[str]
    # Final report
    final_report: str
    # Current task
    current_task: str
