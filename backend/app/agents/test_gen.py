from ..graph.state import AgentState


class TestGenAgent:
    @staticmethod
    def run(state: AgentState):
        print("--- TEST GENERATOR ---")
        return {
            "test_results": ["Tests: Pytest cases generated for all functions in KG."]
        }
