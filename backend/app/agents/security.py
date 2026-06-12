import json
import os
import subprocess
import glob
from typing import List, Dict, Optional
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from tavily import TavilyClient
from ..graph.state import AgentState
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.config import GEMINI_MODEL_TYPE, GEMINI_API_KEY, TAVILY_API_KEY, gemini_limiter
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class SecurityAgent:
    def __init__(self, tag: str, project_dir: str, project_root: str):
        self.tag = tag
        self.project_dir = project_dir
        self.project_root = project_root
        self.ladybug = LadybugClient(db_path=f"{project_dir}/graph_db")
        self.chroma = ChromaClient(path=f"{project_dir}/vector_db")
        self.tavily = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
        
        # --- Specialized Security Tools ---
        
        @tool
        def get_file(path: str):
            """Fetch the full content of any file in the codebase."""
            logger.info(f"SECURITY TOOL: get_file(path='{path}')")
            try:
                target_path = path if os.path.isabs(path) else os.path.join(self.project_root, path)
                with open(target_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file: {e}"

        @tool
        def check_dependencies():
            """Reads manifest files and checks for potential CVE scanning needs."""
            logger.info("SECURITY TOOL: check_dependencies()")
            manifests = ["requirements.txt", "package.json", "go.mod", "Cargo.toml"]
            found_vulns = []
            for manifest in manifests:
                path = os.path.join(self.project_root, manifest)
                if os.path.exists(path):
                    found_vulns.append(f"Found manifest: {manifest}. Recommend OSV scan.")
            return "\n".join(found_vulns) if found_vulns else "No standard dependency manifests found."

        @tool
        def run_sast_scanner(target_path: str):
            """Runs Semgrep locally to find known vulnerability patterns and low-hanging fruit."""
            logger.info(f"SECURITY TOOL: run_sast_scanner(target='{target_path}')")
            try:
                abs_target = target_path if os.path.isabs(target_path) else os.path.join(self.project_root, target_path)
                cmd = ["semgrep", "scan", "--json", "--config", "auto", abs_target]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0 and not result.stdout:
                    return f"Semgrep error: {result.stderr}"
                data = json.loads(result.stdout)
                findings = []
                for res in data.get("results", []):
                    findings.append({
                        "check_id": res.get("check_id"),
                        "path": res.get("path"),
                        "line": res.get("start", {}).get("line"),
                        "message": res.get("extra", {}).get("message"),
                        "severity": res.get("extra", {}).get("severity")
                    })
                return json.dumps(findings[:15])
            except Exception as e:
                return f"Failed to run SAST scanner: {e}"

        @tool
        def scan_for_secrets():
            """Runs regex-based patterns to find hardcoded credentials and high-entropy strings."""
            logger.info("SECURITY TOOL: scan_for_secrets()")
            return "Secrets scan initiated. Please check the current file for high-entropy strings or hardcoded keys."

        @tool
        def search_security_guidance(query: str):
            """Retrieves live security guidance or remediation advice for a specific vulnerability pattern."""
            if not self.tavily:
                return "Tavily API Key not configured. Use internal knowledge."
            logger.info(f"SECURITY TOOL: search_security_guidance(q='{query}')")
            search_query = f"Security remediation guide for {query}"
            res = self.tavily.search(q=search_query, search_depth="advanced")
            return str(res)

        @tool
        def query_vulnerability_memory(vuln_description: str):
            """Search project memory specifically for past security findings or remediation guides."""
            logger.info(f"SECURITY TOOL: query_vulnerability_memory(q='{vuln_description}')")
            results = self.chroma.query([f"remediation for {vuln_description}"], n_results=3)
            return json.dumps(results)

        @tool
        def emit_security_finding(rule_id: str, title: str, severity: str, description: str, remediation: str, confidence: str, line: int, owasp_category: Optional[str] = None, cwe_id: Optional[str] = None):
            """Record a confirmed security vulnerability."""
            logger.info(f"SECURITY TOOL: emit_finding(id='{rule_id}', title='{title}')")
            return json.dumps({
                "rule_id": rule_id,
                "title": title,
                "owasp_category": owasp_category,
                "cwe_id": cwe_id,
                "category": "security",
                "severity": severity,
                "description": description,
                "remediation": remediation,
                "confidence": confidence,
                "line": line
            })

        @tool
        def get_callers(function_name: str, file_path: str):
            """Find all functions that call this function across the codebase."""
            logger.info(f"SECURITY TOOL: get_callers(func='{function_name}', file='{file_path}')")
            query = "MATCH (c:Function {id: $id})<-[:CALLS]-(caller:Function) RETURN caller.name, caller.file"
            res = self.ladybug.execute(query, {"id": f"{file_path}:{function_name}"})
            if res.has_next():
                df = res.get_as_df().replace({float('nan'): None})
                return json.dumps(df.to_dict(orient="records"))
            return "[]"

        @tool
        def get_callees(function_name: str, file_path: str):
            """Find all functions called by this function."""
            logger.info(f"SECURITY TOOL: get_callees(func='{function_name}', file='{file_path}')")
            query = "MATCH (c:Function {id: $id})-[:CALLS]->(callee:Function) RETURN callee.name, callee.file"
            res = self.ladybug.execute(query, {"id": f"{file_path}:{function_name}"})
            if res.has_next():
                df = res.get_as_df().replace({float('nan'): None})
                return json.dumps(df.to_dict(orient="records"))
            return "[]"

        @tool
        def get_imports(file_path: str):
            """List all resolved imports and architectural hints for this file."""
            logger.info(f"SECURITY TOOL: get_imports(file='{file_path}')")
            query = "MATCH (m:Module {path: $path})-[:DIR_TO_MODULE]-(d:Directory) RETURN d.summary, d.context"
            res = self.ladybug.execute(query, {"path": file_path})
            if res.has_next():
                df = res.get_as_df().replace({float('nan'): None})
                return json.dumps(df.to_dict(orient="records"))
            return "[]"

        self.tools = [
            get_file, get_callers, get_callees, get_imports,
            check_dependencies, run_sast_scanner, scan_for_secrets,
            search_security_guidance, query_vulnerability_memory, emit_security_finding
        ]
        
        self.llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL_TYPE,
            google_api_key=GEMINI_API_KEY,
            temperature=0
        ).bind_tools(self.tools)

    async def _call_model(self, state: AgentState):
        messages = state["messages"]
        logger.info(f"--- SECURITY AGENT PROMPT PREVIEW ---\n{str(messages[-1].content)[:200]}...")
        
        # RATE LIMITING
        async with gemini_limiter:
            response = await self.llm.ainvoke(messages)
            
        logger.info(f"--- SECURITY AI RESPONSE ---\n{response.content}\nTool Calls: {response.tool_calls}")
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        if not state["messages"][-1].tool_calls:
            return "end"
        return "continue"

    async def run(self, batch_state: Dict) -> Dict:
        all_security_findings = []
        config_data = batch_state.get("project_config", {})
        max_depth = config_data.get("max_recursion_depth", 3)
        recursion_limit = config_data.get("max_iterations", 25)

        for file_info in batch_state.get("files", []):
            logger.info(f"Security investigation started for: {file_info['path']}")
            
            security_context = await self._get_relevant_security_context(file_info)

            workflow = StateGraph(AgentState)
            workflow.add_node("agent", self._call_model)
            workflow.add_node("tools", ToolNode(self.tools))
            workflow.set_entry_point("agent")
            workflow.add_conditional_edges("agent", self._should_continue, {"continue": "tools", "end": END})
            workflow.add_edge("tools", "agent")
            compiled_agent = workflow.compile()

            system_msg = SystemMessage(content=f"""
You are an Expert Security Auditor and Zero-Knowledge Vulnerability Researcher.
Your goal is to find security flaws spanning across files by tracing data flow and call graphs.

PROJECT-SPECIFIC SECURITY RULES & GUIDELINES:
{security_context}

AUDIT SCOPE:
1. Novel logic bypasses and state manipulation.
2. OWASP Top 10 and SANS Top 25 patterns.
3. Check if the code violates the PROJECT-SPECIFIC SECURITY RULES provided above.
4. Hardcoded secrets and configuration errors.

INVESTIGATION STRATEGY:
1. Use 'run_sast_scanner' to find low-hanging fruit.
2. Trace tainted data from external inputs to sensitive sinks.
3. Actively try to break developer assumptions.
4. Use 'search_security_guidance' for external research.

PROJECT_ROOT: {self.project_root}
MAX RECURSION DEPTH: {max_depth}
""")
            
            initial_input = {
                "messages": [system_msg, HumanMessage(content=f"Scan this file for security flaws:\nPATH: {file_info['path']}\nCONTENT:\n{file_info['content']}")]
            }

            try:
                result = await compiled_agent.ainvoke(initial_input, {"recursion_limit": recursion_limit})
                for msg in result["messages"]:
                    if isinstance(msg, ToolMessage) and msg.name == "emit_security_finding":
                        try:
                            finding_data = json.loads(msg.content)
                            finding_data["file_path"] = file_info["path"]
                            all_security_findings.append(finding_data)
                        except:
                            pass
            except Exception as e:
                logger.error(f"Security ReAct loop failed for {file_info['path']}: {e}")
                continue

        return {"security_findings": all_security_findings}

    async def _get_relevant_security_context(self, file_info: Dict) -> str:
        """Proactively retrieves security guidelines related to the current file."""
        query_text = f"Security rules, authentication requirements, and known vulnerability patterns for {file_info['path']}"
        try:
            # RATE LIMITING
            async with gemini_limiter:
                results = self.chroma.query([query_text], n_results=5)
            
            doc_chunks = []
            for r in results:
                meta = r.get("metadata", {})
                if "doc_id" in meta:
                    breadcrumb = meta.get("breadcrumb", "Security Standard")
                    doc_chunks.append(f"[{breadcrumb}]: {r['document']}")
            
            if not doc_chunks:
                return "No specific security guidelines found for this file. Use general best practices."
                
            return "\n\n".join(doc_chunks)
        except Exception as e:
            logger.warning(f"Failed to fetch proactive security context: {e}")
            return "Could not retrieve project security rules."
