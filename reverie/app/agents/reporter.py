import os
import json
from pathlib import Path
from datetime import datetime
from ..graph.state import AgentState
from ..core.config import get_project_dir
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class ReporterAgent:
    @staticmethod
    def run(state: AgentState):
        logger.info("--- REPORTER AGENT STARTING ---")

        bugs = state.get("bug_findings", [])
        security = state.get("security_findings", [])
        smells = state.get("smell_findings", [])
        tests = state.get("generated_tests", [])

        logger.info(
            f"Aggregated Findings: {len(bugs)} bugs, {len(security)} security, {len(smells)} smells"
        )

        # --- 1. Generate Markdown Report ---
        report_md = ReporterAgent._generate_markdown(
            state, bugs, security, smells, tests
        )

        # --- 2. Generate SARIF Report ---
        sarif_data = ReporterAgent._generate_sarif(state, bugs, security, smells)

        # --- 3. Save Reports ---
        ReporterAgent._save_reports(state, report_md, sarif_data)

        logger.info("--- REPORTER AGENT COMPLETE ---")
        return {"final_report": report_md}

    @staticmethod
    def _generate_markdown(state, bugs, security, smells, tests):
        report = [
            f"# Review Report for {state['project_tag']}",
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Mode: {state.get('review_mode', 'unknown')}\n",
            f"## Summary",
            f"- **Bugs Found**: {len(bugs)}",
            f"- **Security Issues**: {len(security)}",
            f"- **Code Smells**: {len(smells)}",
            f"- **Tests Generated**: {len(tests)}\n",
        ]

        if bugs:
            report.append("## Bug Findings")
            for b in bugs:
                report.append(f"### {b['title']} ({b.get('severity', 'medium')})")
                report.append(f"File: {b['file_path']} (Line {b.get('line', 1)})")
                report.append(f"{b['description']}\n")

        if security:
            report.append("## Security Vulnerabilities")
            for s in security:
                owasp = f" | {s['owasp_category']}" if s.get("owasp_category") else ""
                report.append(f"### {s['title']} ({s['severity']}{owasp})")
                report.append(f"**Confidence**: {s.get('confidence', 'medium')}")
                report.append(f"File: {s['file_path']} (Line {s.get('line', 1)})")
                report.append(f"**Description**: {s['description']}")
                report.append(f"**Remediation**: {s.get('remediation', 'N/A')}\n")

        if smells:
            report.append("## Code Smells & Technical Debt")
            for sm in smells:
                report.append(
                    f"### {sm['title']} (Complexity: {sm.get('complexity_score', 5)}/10)"
                )
                report.append(f"File: {sm['file_path']} (Line {sm.get('line', 1)})")
                report.append(f"**Description**: {sm['description']}")
                report.append(f"**Suggestion**: {sm.get('remediation', 'N/A')}\n")

        return "\n".join(report)

    @staticmethod
    def _generate_sarif(state, bugs, security, smells):
        results = []
        all_findings = [
            (bugs, "bug", "error"),
            (security, "security", "error"),
            (smells, "smell", "warning"),
        ]

        for findings, category, level in all_findings:
            for f in findings:
                results.append(
                    {
                        "ruleId": f.get("rule_id")
                        or f"{category.upper()}-{f['title'].replace(' ', '-')}",
                        "level": level
                        if f.get("severity") in ["high", "critical"]
                        else "warning",
                        "message": {"text": f"{f['title']}: {f['description']}"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {
                                        "uri": f["file_path"]
                                        .replace(state.get("project_root", ""), "")
                                        .lstrip("/")
                                    },
                                    "region": {"startLine": f.get("line", 1)},
                                }
                            }
                        ],
                    }
                )

        return {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Reverie AI",
                            "version": "1.0.0",
                            "informationUri": "https://github.com/reverie-ai",
                        }
                    },
                    "results": results,
                }
            ],
        }

    @staticmethod
    def _save_reports(state, markdown_content, sarif_dict):
        try:
            tag = state["project_tag"]
            project_dir = get_project_dir(tag)
            reports_dir = project_dir / "reports"
            reports_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # 1. Save to project isolated storage (always)
            md_filename = f"report_{timestamp}.md"
            sarif_filename = f"results_{timestamp}.sarif"

            with open(reports_dir / md_filename, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            with open(reports_dir / sarif_filename, "w", encoding="utf-8") as f:
                f.write(json.dumps(sarif_dict, indent=2))

            logger.info(f"Project reports archived in: {reports_dir}")

            # 2. Handle Custom Output Directory or CWD
            custom_output_dir = state.get("output_dir")
            if custom_output_dir:
                out_path = Path(custom_output_dir)
                out_path.mkdir(parents=True, exist_ok=True)

                with open(out_path / md_filename, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                with open(out_path / sarif_filename, "w", encoding="utf-8") as f:
                    f.write(json.dumps(sarif_dict, indent=2))

                logger.info(f"Reports exported to custom directory: {out_path}")
            else:
                # Fallback: Save latest SARIF to current working directory
                cwd_sarif = Path.cwd() / f"reverie_results_{timestamp}.sarif"
                with open(cwd_sarif, "w", encoding="utf-8") as f:
                    f.write(json.dumps(sarif_dict, indent=2))

                logger.info(f"Latest SARIF exported to CWD: {cwd_sarif}")

        except Exception as e:
            logger.error(f"CRITICAL: Failed to save reports: {e}", exc_info=True)
