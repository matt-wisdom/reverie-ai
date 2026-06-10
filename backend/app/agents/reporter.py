from ..graph.state import AgentState

class ReporterAgent:
    @staticmethod
    def run(state: AgentState):
        print("--- REPORTER AGENT ---")
        report = (
            f"## Final Analysis Report\n\n"
            f"### Code Review\n{state['review_results'][0]}\n\n"
            f"### Security Scan\n{state['vulnerability_results'][0]}\n\n"
            f"### Test Generation\n{state['test_results'][0]}"
        )
        return {"final_report": report}
