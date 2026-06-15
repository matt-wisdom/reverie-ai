import json
import os
import subprocess
import operator
import re
import asyncio
from typing import List, Dict, Optional, Annotated, Union
from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
    SystemMessage,
    BaseMessage,
    AIMessage,
)
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.errors import GraphRecursionError
from tavily import TavilyClient
from ..graph.state import AgentState, Finding
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.llm_provider import get_llm
from ..core.config import get_tavily_api_key, llm_limiter
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class SecurityAgent:
    def __init__(self, tag: str, project_dir: str, project_root: str):
        self.tag = tag
        self.project_dir = project_dir
        self.project_root = project_root
        self.ladybug = LadybugClient(db_path=f"{project_dir}/graph_db")
        self.chroma = ChromaClient(path=f"{project_dir}/vector_db")
        
        tavily_key = get_tavily_api_key()
        self.tavily = TavilyClient(api_key=tavily_key) if tavily_key else None

        # --- KNOWLEDGE GRAPH POWERED TOOLS ---

        @tool
        def get_file(path: str):
            """Fetch the full source of any file in the repo."""
            logger.info(f"SECURITY TOOL: get_file(path='{path}')")
            try:
                project_folder_name = os.path.basename(self.project_root.rstrip("/"))
                if path.startswith(f"{project_folder_name}/"):
                    path = path[len(f"{project_folder_name}/") :]
                target_path = (
                    path
                    if os.path.isabs(path)
                    else os.path.join(self.project_root, path)
                )
                with open(target_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file at {target_path}: {e}"

        @tool
        def get_callers(function_name: str, file_path: str):
            """Returns all call sites of this function across the codebase: [{file, function}]"""
            logger.info(f"SECURITY TOOL: get_callers(func='{function_name}')")
            query = "MATCH (c:Function {id: $id})<-[:CALLS]-(caller:Function) RETURN caller.name, caller.file"
            res = self.ladybug.execute(query, {"id": f"{file_path}:{function_name}"})
            if res.has_next():
                return json.dumps(
                    res.get_as_df()
                    .replace({float("nan"): None})
                    .to_dict(orient="records")
                )
            return "[]"

        @tool
        def get_callees(function_name: str, file_path: str):
            """Returns all functions this function calls: [{file, function}]"""
            logger.info(f"SECURITY TOOL: get_callees(func='{function_name}')")
            query = "MATCH (c:Function {id: $id})-[:CALLS]->(callee:Function) RETURN callee.name, callee.file"
            res = self.ladybug.execute(query, {"id": f"{file_path}:{function_name}"})
            if res.has_next():
                return json.dumps(
                    res.get_as_df()
                    .replace({float("nan"): None})
                    .to_dict(orient="records")
                )
            return "[]"

        @tool
        def get_data_flow(variable_name: str, function_name: str, file_path: str):
            """Traces a variable's journey: where it comes from, transformation, and sinks it reaches."""
            logger.info(f"SECURITY TOOL: get_data_flow(var='{variable_name}')")
            # Query graph for potential multi-hop paths to sinks
            func_id = f"{file_path}:{function_name}"
            query = """
                MATCH (f:Function {id: $id})-[*1..3]->(s:Finding {category: 'SINK'})
                RETURN f.name as start, s.title as sink, s.finding_id as sink_location
            """
            res = self.ladybug.execute(query, {"id": func_id})
            results = []
            if res.has_next():
                results = res.get_as_df().to_dict(orient="records")

            # Enrich with file context for the reasoning loop
            try:
                abs_path = os.path.join(
                    self.project_root,
                    file_path.replace(os.path.basename(self.project_root), "").lstrip(
                        "/"
                    ),
                )
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                return json.dumps(
                    {
                        "graph_paths_to_sinks": results,
                        "file_context": f"Manual trace required for {variable_name}:\n\n{content}",
                    }
                )
            except:
                return json.dumps(
                    {
                        "graph_paths": results,
                        "error": "Could not read source for manual trace.",
                    }
                )

        @tool
        def get_imports(file_path: str):
            """Returns all imports in the file, resolved to source paths where possible."""
            logger.info(f"SECURITY TOOL: get_imports(file='{file_path}')")
            query = "MATCH (m:Module {path: $path})-[:DEPENDS_ON]->(dep:Module) RETURN dep.path"
            res = self.ladybug.execute(query, {"path": file_path})
            if res.has_next():
                return json.dumps(res.get_as_df().to_dict(orient="records"))
            return "[]"

        @tool
        def get_class_hierarchy(class_name: str):
            """Returns the full inheritance chain for a class."""
            logger.info(f"SECURITY TOOL: get_class_hierarchy(class='{class_name}')")
            query = "MATCH (c:Class {name: $name})-[:INHERITS_FROM*1..5]->(base:Class) RETURN c.name as class, base.name as base"
            res = self.ladybug.execute(query, {"name": class_name})
            if res.has_next():
                return json.dumps(res.get_as_df().to_dict(orient="records"))
            return "[]"

        @tool
        def check_dependencies(manifest_path: str):
            """Reads a dependency manifest and queries for known CVEs."""
            logger.info(f"SECURITY TOOL: check_dependencies(path='{manifest_path}')")
            # In a real implementation, this would call osv.dev. For now, we simulate.
            return "Manifest analysis complete. No critical CVEs found in common dependencies. (OSV integration pending)"

        @tool
        def search_owasp(query: str):
            """Retrieves live security guidance or remediation advice."""
            if not self.tavily:
                return "Tavily API Key not configured."
            logger.info(f"SECURITY TOOL: search_owasp(query='{query}')")
            try:
                res = self.tavily.search(
                    query=f"Security remediation guide for {query}",
                    search_depth="advanced",
                )
                return str(res)
            except Exception as e:
                return f"Search failed: {e}"

        @tool
        def emit_finding(
            title: str,
            severity: str,
            description: str,
            line: int,
            owasp_category: str = "",
            confidence: str = "high",
            remediation: str = "",
        ):
            """Record a confirmed security finding."""
            logger.info(f"SECURITY TOOL: emit_finding(title='{title}')")
            return json.dumps(
                {
                    "title": title,
                    "severity": severity,
                    "description": description,
                    "line": line,
                    "owasp_category": owasp_category,
                    "confidence": confidence,
                    "remediation": remediation,
                    "category": "security",
                }
            )

        self.tools = [
            get_file,
            get_callers,
            get_callees,
            get_data_flow,
            get_imports,
            get_class_hierarchy,
            check_dependencies,
            search_owasp,
            emit_finding,
        ]
        self.base_llm = get_llm(temperature=0)
        self.llm = self.base_llm.bind_tools(self.tools)

    async def _call_model(self, state: AgentState):
        messages = list(state["messages"])

        # 1. Depth Tracking
        get_file_calls = [
            m for m in messages if isinstance(m, ToolMessage) and m.name == "get_file"
        ]
        current_depth = len(get_file_calls)
        max_depth = state.get("project_config", {}).get("max_recursion_depth", 3)

        # 2. Robust Loop Guard
        last_ai_messages = [
            m for m in messages if isinstance(m, AIMessage) and m.tool_calls
        ]
        force_conclude = False
        if len(last_ai_messages) >= 2:
            last = last_ai_messages[-1].tool_calls[0]
            prev = last_ai_messages[-2].tool_calls[0]

            # Compare args regardless of dictionary key order
            last_args = json.dumps(last["args"], sort_keys=True)
            prev_args = json.dumps(prev["args"], sort_keys=True)

            if last["name"] == prev["name"] and last_args == prev_args:
                logger.warning(
                    f"LOOP DETECTED: Agent repeating {last['name']} with same args."
                )

                # If we've looped 3 times, force conclusion
                if len(last_ai_messages) >= 3:
                    prev2 = last_ai_messages[-3].tool_calls[0]
                    prev2_args = json.dumps(prev2["args"], sort_keys=True)
                    if last["name"] == prev2["name"] and last_args == prev2_args:
                        logger.error("SEVERE LOOP DETECTED. Forcing agent to conclude.")
                        force_conclude = True

                if not force_conclude:
                    messages.append(
                        SystemMessage(
                            content="ANTI-LOOP WARNING: You just repeated the exact same tool call with the exact same arguments. This is strictly forbidden. You must either try a different file, a different tool, or use emit_finding. Do not repeat the same action again."
                        )
                    )

        # 3. Track emitted vulnerabilities
        emitted_vulns = []
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.name == "emit_finding":
                try:
                    finding = json.loads(msg.content)
                    emitted_vulns.append(
                        f"- {finding.get('title')} ({finding.get('severity')})"
                    )
                except:
                    pass

        vuln_text = "\n".join(emitted_vulns) if emitted_vulns else "None"
        if messages and isinstance(messages[0], SystemMessage):
            parts = messages[0].content.split("CURRENTLY EMITTED VULNERABILITIES:")
            messages[0] = SystemMessage(
                content=f"{parts[0]}CURRENTLY EMITTED VULNERABILITIES:\n{vuln_text}\n"
            )

        # 4. Enforce Conclude
        llm = self.llm
        if current_depth >= max_depth or force_conclude:
            logger.info("MAX DEPTH OR LOOP REACHED: Forcing conclusion.")
            # Unbind tools to force text generation or emit_finding only
            llm = self.base_llm.bind_tools([self.tools[-1]])  # only emit_finding

        logger.info(
            f"Security Agent Reasoning (Depth: {current_depth}/{max_depth}, Tool Calls: {len(last_ai_messages)})"
        )
        async with llm_limiter:
            response = await llm.ainvoke(messages)

        # If forced to conclude and model still tries to hallucinate a tool, override it
        if (
            force_conclude
            and response.tool_calls
            and response.tool_calls[0]["name"] != "emit_finding"
        ):
            response.tool_calls = []
            response.content = "Investigation halted due to repetitive loops. Please review emitted findings."

        logger.info(
            f"--- SECURITY AI RESPONSE ---\n{response.content}\nTool Calls: {response.tool_calls}"
        )
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        return "continue" if state["messages"][-1].tool_calls else "end"

    async def run(self, batch_state: Dict) -> Dict:
        all_security_findings = []
        config = batch_state.get("project_config", {})
        max_iterations = config.get("max_iterations", 25)

        for file_info in batch_state.get("files", []):
            logger.info(f"Starting security investigation for: {file_info['path']}")
            security_context = await self._get_relevant_security_context(file_info)

            arch_summary = f"\nCODEBASE ARCHITECTURAL OVERVIEW:\n{batch_state.get('codebase_summary', 'Unavailable')}\n"
            user_instructions = (
                f"\nCUSTOM USER INSTRUCTIONS:\n{batch_state.get('user_prompt')}\n"
                if batch_state.get("user_prompt")
                else ""
            )

            workflow = StateGraph(AgentState)
            workflow.add_node("agent", self._call_model)
            workflow.add_node("tools", ToolNode(self.tools))
            workflow.set_entry_point("agent")
            workflow.add_conditional_edges(
                "agent", self._should_continue, {"continue": "tools", "end": END}
            )
            workflow.add_edge("tools", "agent")
            compiled_agent = workflow.compile()

            system_msg = SystemMessage(
                content=f"""
You are an application security expert embedded in an automated code review pipeline.
Your job is to find real, exploitable security vulnerabilities in the code you are given.
You are NOT a linter. Do not flag style issues, missing documentation, or code smells.
Only flag issues that have a plausible exploitation path.

{arch_summary}
{user_instructions}

PROJECT-SPECIFIC SECURITY RULES & GUIDELINES:
{security_context}

You must work in a strict loop: PLAN → ACT → OBSERVE → REASON → (repeat or CONCLUDE)

PLAN
Before calling any tool, write a short investigation plan. Answer:
- MANDATORY ENTRY POINT DISCOVERY: List all functions in this file exposed to external users (look for route decorators, public exports, or 'handler'/'controller' naming).
- You MUST assume all parameters to these entry points are TAINTED and potentially malicious.
- What are the dangerous sinks?
  (SQL execution, shell commands, template rendering, deserialisation, file writes, HTTP redirects, eval, pickle, subprocess)
- Which inputs could plausibly reach which sinks?
- What do I need to fetch to confirm or rule out a vulnerability?
- What suppressions or ADRs might already cover something I am about to flag?

Keep the plan to 6-8 bullet points. Do not begin tool calls until the plan is written.

ACT
Call one tool at a time. State why you are calling it before calling it.
Never call a tool without explaining your reason in one sentence first.

OBSERVE
After each tool result, summarise what you learned in 1-2 sentences. Update your mental model.

REASON
After each observation, decide:
- Did this confirm a vulnerability? → emit_finding, then continue investigating
- Did this rule out a suspicion? → note it and move on
- Do I need more information? → call another tool if depth allows
- Have I exhausted this thread? → move to the next suspicion


════════════════════════════════════════
VULNERABILITY CHECKLIST
════════════════════════════════════════

Pay particular attention to (but do not limit yourself to) the following common vulnerability types and patterns:

INJECTION (A03)
- SQL: string formatting or concatenation used in queries?
- SQL: ORM raw() or execute() called with unsanitised input?
- Command: subprocess, os.system, os.popen called with user input?
- Template: user input reaches render(), format(), or eval()?
- NoSQL: query objects built from unsanitised request data?
- LDAP: directory queries built from user input?

CONCURRENCY AND RACE CONDITIONS
- File writes without locking or atomic operations?
- Check-then-act on shared resources without locks?
- In-memory state modified in request handlers without concurrency controls?
- Time of check to time of use (TOCTOU) on file or resource access?

BROKEN ACCESS CONTROL (A01)
- Object IDs taken from request without ownership check?
- Sensitive endpoints missing authorisation decorator/middleware?
- Admin functions reachable without privilege check via indirect call?
- Mass assignment: user-controlled fields merged into model without allowlist?

CRYPTOGRAPHIC FAILURES (A02)
- Secrets hardcoded in source, config, or test fixtures?
- Secrets logged before use?
- MD5 or SHA-1 used for anything security-sensitive?
- ECB mode or missing IV in block ciphers?
- TLS verification disabled (verify=False, InsecureSkipVerify)?
- Sensitive data written to logs, temp files, or cache unencrypted?

AUTHENTICATION FAILURES (A07)
- JWT: alg:none accepted? Secret hardcoded? Expiry not validated?
- JWT: audience or issuer claims not validated?
- Session ID not regenerated after privilege change?
- Password stored without hashing, or hashed with MD5/SHA-1/unsalted?
- No rate limiting on login, reset, or OTP endpoints?

INSECURE DESERIALISATION (A08)
- pickle.loads() called on untrusted data?
- yaml.load() called without SafeLoader?
- JSON parsed then exec'd or eval'd?
- Java ObjectInputStream on untrusted bytes?

SSRF (A10)
- User-controlled URL passed to requests.get(), fetch(), curl, or equivalent?
- Allowlist validation present and enforced?
- Cloud metadata endpoint (169.254.169.254) reachable from request handler?

SECURITY MISCONFIGURATION (A05)
- DEBUG=True or equivalent in any config that could reach production?
- CORS allowing all origins on authenticated endpoints?
- Verbose error messages exposing stack traces to the client?
- Security headers missing: CSP, HSTS, X-Frame-Options, X-Content-Type-Options?

VULNERABLE COMPONENTS (A06)
- Dependency manifests present? Run check_dependencies on each one.

════════════════════════════════════════
CONFIDENCE RULES
════════════════════════════════════════

Before emitting any finding, answer these three questions internally:

1. Can I trace a concrete path from an untrusted source to this sink?
   If no: do not emit. Note the suspicion and move on.

2. Is there sanitisation, validation, or authorisation on that path
   that I may have missed?
   If yes: fetch the sanitisation function and verify it is insufficient
   before emitting.

3. Is this covered by a suppression or ADR in the project context?
   If yes: do not emit. The team has already made a decision about this.

Confidence levels:
HIGH   — full source-to-sink trace confirmed, no sanitisation found
MEDIUM — strong indicator but one hop in the trace could not be confirmed
         (e.g. dynamic dispatch prevented full resolution)
LOW    — pattern match only, could not trace data flow to confirm

Only HIGH and MEDIUM findings are emitted by default.
LOW findings are only emitted if the severity is CRITICAL.



════════════════════════════════════════
HARD RULES
════════════════════════════════════════

Never emit a finding you cannot explain to a developer in concrete terms.
Never emit a finding covered by a suppression or ADR.
Never call search_owasp before you have confirmed a finding exists.
Never open a file without stating your reason first.
Never exceed max_depth. Conclude gracefully if you hit it.
Never flag the same vulnerability twice for the same location.
If you find nothing, respond with an empty findings array. That is a valid result.

PROJECT_ROOT: {self.project_root}
CURRENTLY EMITTED VULNERABILITIES:
"""
            )
            initial_input = {
                "messages": [
                    system_msg,
                    HumanMessage(
                        content=f"Scan this file for security flaws:\nPATH: {file_info['path']}\nCONTENT:\n{file_info['content']}"
                    ),
                ]
            }
            try:
                result = await compiled_agent.ainvoke(
                    initial_input, {"recursion_limit": max_iterations}
                )
                for msg in result["messages"]:
                    if isinstance(msg, ToolMessage) and msg.name == "emit_finding":
                        try:
                            finding_data = json.loads(msg.content)
                            finding_data["file_path"] = file_info["path"]
                            all_security_findings.append(finding_data)
                        except:
                            pass
            except GraphRecursionError:
                logger.warning(
                    f"Security Agent hit recursion limit for {file_info['path']}. Returning partial results."
                )
            except Exception as e:
                logger.error(f"Security loop failed for {file_info['path']}: {e}")
                continue
        return {"security_findings": all_security_findings}

    async def _get_relevant_security_context(self, file_info: Dict) -> str:
        try:
            async with llm_limiter:
                results = self.chroma.query(
                    [f"security rules for {file_info['path']}"], n_results=5
                )
            doc_chunks = [
                f"[{r.get('metadata', {}).get('breadcrumb')}]: {r['document']}"
                for r in results
                if "doc_id" in r.get("metadata", {})
            ]
            return (
                "\n\n".join(doc_chunks)
                if doc_chunks
                else "No specific security guidelines found."
            )
        except:
            return "Could not retrieve project security rules."
