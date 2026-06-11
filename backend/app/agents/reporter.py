from ..graph.state import AgentState


class ReporterAgent:
    @staticmethod
    def run(state: AgentState):
        print("--- REPORTER AGENT ---")

        bugs = state.get("bug_findings", [])
        security = state.get("security_findings", [])
        smells = state.get("smell_findings", [])
        tests = state.get("generated_tests", [])

        report = [
            f"# Review Report for {state['project_tag']}",
            f"Mode: {state['review_mode']}\n",
            f"## Summary",
            f"- **Bugs Found**: {len(bugs)}",
            f"- **Security Issues**: {len(security)}",
            f"- **Code Smells**: {len(smells)}",
            f"- **Tests Generated**: {len(tests)}\n",
        ]

        if bugs:
            report.append("## Bug Findings")
            for b in bugs:
                report.append(f"### {b['title']} ({b['severity']})")
                report.append(f"File: {b['file_path']} (Line {b['line']})")
                report.append(f"{b['description']}\n")

        # ... (similar sections for security/smells could be added)

        return {"final_report": "\n".join(report)}
