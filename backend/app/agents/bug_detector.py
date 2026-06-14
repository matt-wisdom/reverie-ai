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
from ..graph.state import AgentState, Finding
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.llm_provider import get_llm
from ..core.config import REVERIE_MAX_ITERATIONS, llm_limiter
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class BugDetectorAgent:
    def __init__(self, tag: str, project_dir: str, project_root: str):
        self.tag = tag
        self.project_dir = project_dir
        self.project_root = project_root
        self.ladybug = LadybugClient(db_path=f"{project_dir}/graph_db")
        self.chroma = ChromaClient(path=f"{project_dir}/vector_db")

        @tool
        def get_file(path: str):
            """Fetch the full content of any file."""
            logger.info(f"BUG TOOL: get_file(path='{path}')")
            try:
                # Strip redundant project root folder names
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
            """Find all functions that call this function."""
            logger.info(
                f"BUG TOOL: get_callers(func='{function_name}', file='{file_path}')"
            )
            project_folder_name = os.path.basename(self.project_root.rstrip("/"))
            if file_path.startswith(f"{project_folder_name}/"):
                file_path = file_path[len(f"{project_folder_name}/") :]
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
            """Find all functions called by this function."""
            logger.info(
                f"BUG TOOL: get_callees(func='{function_name}', file='{file_path}')"
            )
            project_folder_name = os.path.basename(self.project_root.rstrip("/"))
            if file_path.startswith(f"{project_folder_name}/"):
                file_path = file_path[len(f"{project_folder_name}/") :]
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
        def emit_finding(title: str, severity: str, description: str, line: int):
            """Record a confirmed bug finding."""
            logger.info(f"BUG TOOL: emit_finding(title='{title}')")
            return json.dumps(
                {
                    "title": title,
                    "category": "bug",
                    "severity": severity,
                    "description": description,
                    "line": line,
                }
            )

        self.tools = [get_file, get_callers, get_callees, emit_finding]
        self.base_llm = get_llm(temperature=0)

    async def _call_model(self, state: AgentState):
        messages = list(state["messages"])

        # 1. Depth Tracking
        get_file_calls = [
            m for m in messages if isinstance(m, ToolMessage) and m.name == "get_file"
        ]
        current_depth = len(get_file_calls)
        max_depth = state.get("project_config", {}).get("max_recursion_depth", 3)

        # 2. Loop Guard: Check for repetitive tool calls
        last_ai_messages = [
            m for m in messages if isinstance(m, AIMessage) and m.tool_calls
        ]
        if len(last_ai_messages) >= 2:
            last = last_ai_messages[-1].tool_calls[0]
            prev = last_ai_messages[-2].tool_calls[0]
            if last["name"] == prev["name"] and last["args"] == prev["args"]:
                logger.warning(
                    f"LOOP DETECTED: Agent repeating {last['name']}. Injecting guardrail."
                )
                messages.append(
                    SystemMessage(
                        content="ANTI-LOOP WARNING: You just repeated the exact same tool call. You must either try a different file, a different tool, or CONCLUDE. Do not repeat the same action again."
                    )
                )

        # 3. Bug Tracking
        emitted_bugs = []
        for msg in messages:
            if isinstance(msg, ToolMessage) and msg.name == "emit_finding":
                try:
                    finding = json.loads(msg.content)
                    emitted_bugs.append(
                        f"- {finding.get('title')} (Line {finding.get('line')})"
                    )
                except:
                    pass

        bug_text = "\n".join(emitted_bugs) if emitted_bugs else "None"

        # Update System Prompt
        if messages and isinstance(messages[0], SystemMessage):
            content = messages[0].content
            content = content.replace("{current_depth}", str(current_depth))
            content = content.split("CURRENTLY EMITTED BUGS:")[0]
            content += f"CURRENTLY EMITTED BUGS:\n{bug_text}\n"
            messages[0] = SystemMessage(content=content)

        # 4. Enforce Conclude at Max Depth by stripping tools
        llm = self.base_llm
        if current_depth >= max_depth:
            logger.info("MAX DEPTH REACHED: Forcing conclusion.")
            llm = llm.bind_tools([self.tools[-1]])  # only emit_finding
        else:
            llm = llm.bind_tools(self.tools)

        logger.info(f"Bug Detector Reasoning (Depth: {current_depth}/{max_depth})")
        async with llm_limiter:
            response = await llm.ainvoke(messages)
        logger.info(
            f"--- BUG AI RESPONSE ---\n{response.content}\nTool Calls: {response.tool_calls}"
        )
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        return "continue" if state["messages"][-1].tool_calls else "end"

    async def run(self, batch_state: Dict) -> Dict:
        all_bug_findings = []
        config = batch_state.get("project_config", {})
        max_iterations = config.get("max_iterations", 25)
        max_depth = config.get("max_recursion_depth", 3)

        for file_info in batch_state.get("files", []):
            logger.info(f"Bug investigation started for: {file_info['path']}")

            arch_summary = f"\nCODEBASE ARCHITECTURAL OVERVIEW:\n{batch_state.get('codebase_summary', 'Unavailable')}\n"
            user_instr = (
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
You are a bug detection expert embedded in an automated code review pipeline.
Your job is to find real bugs — code that will malfunction, crash, corrupt data,
or behave incorrectly at runtime.

You are NOT a security scanner. Do not flag injection flaws, auth issues, or CVEs.
You are NOT a linter. Do not flag style issues, naming conventions, or formatting.
Only flag issues that will cause incorrect behaviour under realistic conditions.

{arch_summary}
{user_instr}

════════════════════════════════════════
HOW TO INVESTIGATE
════════════════════════════════════════
Follow this loop: PLAN → ACT → OBSERVE → REASON → (repeat or CONCLUDE)

PLAN
Before calling any tool, write a short investigation plan. Answer:
- What are the inputs to the functions in this file?
  (parameters, return values from calls, global state, file/network I/O)
- What assumptions does the code make about those inputs?
  (type, range, nullability, ordering, timing)
- Where could those assumptions be violated?
- What would happen at runtime if they were?
- Which suppressions or ADRs might already cover something I am about to flag?
Keep the plan to 6-8 bullet points. Do not begin tool calls until the plan is written.

ACT
Call one tool at a time. State your reason in one sentence before each call.

OBSERVE
After each tool result, summarise in 1-2 sentences what you learned and how it updates your understanding of the bug candidate.

REASON
After each observation decide:
- Does this confirm the bug? → emit_finding, then continue
- Does this rule it out? → note why and move on
- Do I need one more piece of information? → call another tool if depth allows
- Have I exhausted this thread? → move to the next candidate

════════════════════════════════════════
DEPTH CONTROL
════════════════════════════════════════
Current depth: {{current_depth}} / {max_depth}

At depth 0-1: Follow any credible lead. Open files freely.
At depth 2:   Only follow leads directly tied to a confirmed or near-confirmed bug.
At depth 3+:  Conclude open threads. Emit confirmed findings. Stop opening files.

If you hit max depth, emit what you have confirmed and note in the description that the trace was truncated at depth {max_depth}.

════════════════════════════════════════
ANTI-LOOP PROTOCOL
════════════════════════════════════════
If a tool call fails, DO NOT call it again with the exact same arguments. Try a different approach or move on.

════════════════════════════════════════
BUG CHECKLIST
════════════════════════════════════════

Work through (but do not limit yourself to) these categories:

NULL AND UNDEFINED REFERENCES
- Attribute or index access on a value that could be None/null/undefined?
- Return value of a function used directly without checking for None/null?
- Optional chaining or null coalescing absent where the type allows null?
- Dictionary/map key access without existence check?

ERROR HANDLING
- Bare except/catch that swallows all exceptions silently?
- Exception caught, logged, and execution continues when it should halt?
- Exception re-raised in a way that loses the original traceback?
- Errors from I/O operations (file, network, db) not handled at all?
- Async errors not caught — unhandled promise rejections, unhandled
  goroutine panics, missing errcheck?

RESOURCE MANAGEMENT
- File handle opened without guaranteed close (no with/using/defer)?
- Database connection or cursor not closed on all exit paths?
- Network socket or HTTP client not closed after use?
- Lock acquired but not released on error paths?
- Goroutine or thread started but never joined or cancelled?

CONCURRENCY
- Shared mutable state accessed from multiple goroutines/threads
  without synchronisation?
- Read-modify-write on shared state without atomicity?
- Class-level or module-level mutable default used as instance state?
- Async function called without await where the result is used?
- Race between check and use (TOCTOU) on a file or resource?

LOGIC ERRORS
- Off-by-one in loop bounds, slice indices, or range calculations?
- Boolean operator precedence producing unexpected short-circuit?
- Inverted condition — == where !=, < where >, and where or?
- Assignment in a conditional where comparison was intended?
- Wrong variable used — similar names, shadowing, or copy-paste error?
- Early return or break that skips necessary cleanup or state update?

TYPE AND VALUE ERRORS
- Integer overflow or underflow under realistic input values?
- Float precision error where exact comparison is used (== on floats)?
- Implicit type coercion producing unexpected behaviour?
- String/bytes confusion — decoding at the wrong point?
- Index into a collection with an unvalidated user-supplied integer?

ALGORITHM CORRECTNESS
- Recursive function missing or incorrectly specified base case?
- Loop that can run zero times when at least one iteration is required?
- Mutation of a collection while iterating over it?
- Sorting that does not handle equal elements or empty input?
- Retry logic that retries on non-retryable errors?
- Timeout that is never enforced or is set to zero?
- Cache that is never invalidated when the underlying data changes?

LANGUAGE-SPECIFIC

Python:
- Mutable default argument (def f(x=[]))?
- Generator exhausted and reused?
- Late binding closure in a loop (lambda: i where i changes)?
- deepcopy omitted where aliasing causes unintended mutation?
- __eq__ implemented without __hash__, breaking set/dict membership?

JavaScript / TypeScript:
- == used where === needed?
- Implicit NaN propagation — arithmetic on undefined?
- Promise created but not returned from an async function?
- Array.sort() without comparator on numeric arrays?
- Event listener added but never removed, causing memory leak?

Go:
- Error return ignored with _?
- Goroutine leak — goroutine started, nothing can stop it?
- Slice append aliasing — append to a slice that shares backing array?
- defer in a loop executing at function return, not loop iteration?
- nil pointer dereference through interface?

Java:
- equals() overridden without hashCode()?
- String comparison with == instead of .equals()?
- Integer cache pitfall — == on boxed integers outside -128..127?
- Checked exception swallowed in catch (Exception e) {{}}?
- Resource not closed — missing try-with-resources?

════════════════════════════════════════
CONFIDENCE RULES
════════════════════════════════════════

Before emitting any finding, answer these internally:

1. Under what realistic input or condition does this bug trigger?
   If you cannot describe a concrete triggering condition: do not emit.

2. What is the actual runtime consequence?
   (crash, wrong output, data corruption, infinite loop, resource exhaustion)
   If the consequence is only theoretical or negligible: do not emit.

3. Is this already handled somewhere I may have missed?
   Fetch the handler and verify it is absent or insufficient before emitting.

4. Is this covered by a suppression or ADR?
   If yes: do not emit

PROJECT_ROOT: {self.project_root}
CURRENTLY EMITTED BUGS:
"""
            )
            initial_input = {
                "messages": [
                    system_msg,
                    HumanMessage(
                        content=f"Investigate for bugs:\nPATH: {file_info['path']}\nCONTENT:\n{file_info['content']}"
                    ),
                ],
                "project_config": config,
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
                            all_bug_findings.append(finding_data)
                        except:
                            pass
            except GraphRecursionError:
                logger.warning(
                    f"Bug Agent hit recursion limit for {file_info['path']}. Returning partial results."
                )
            except Exception as e:
                logger.error(f"Bug loop failed for {file_info['path']}: {e}")
                continue
        return {"bug_findings": all_bug_findings}

    async def _get_relevant_context(self, file_info: Dict) -> str:
        try:
            async with llm_limiter:
                results = self.chroma.query(
                    [f"rules for {file_info['path']}"], n_results=5
                )
            doc_chunks = [
                f"[{r.get('metadata', {}).get('breadcrumb')}]: {r['document']}"
                for r in results
                if "doc_id" in r.get("metadata", {})
            ]
            return "\n\n".join(doc_chunks) if doc_chunks else "No specific rules found."
        except:
            return "Could not retrieve project context."
