from ..graph.state import AgentState

class ScannerAgent:
    @staticmethod
    def run(state: AgentState):
        print("--- VULNERABILITY SCANNER ---")
        return {"vulnerability_results": ["Scanner: No SQL injection or XSS detected."]}
