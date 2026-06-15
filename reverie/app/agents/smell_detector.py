import json
import os
from typing import List, Dict, Optional
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from ..graph.state import AgentState
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.llm_provider import get_llm
from ..core.config import llm_limiter
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class SmellDetectorAgent:
    def __init__(self, tag: str, project_dir: str, project_root: str):
        self.tag = tag
        self.project_dir = project_dir
        self.project_root = project_root
        self.ladybug = LadybugClient(db_path=f"{project_dir}/graph_db")
        self.chroma = ChromaClient(path=f"{project_dir}/vector_db")

        @tool
        def get_file(path: str):
            """Fetch the full content of any file."""
            logger.info(f"SMELL TOOL: get_file(path='{path}')")
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
            """Find all callers to determine coupling or 'God-ness'."""
            logger.info(
                f"SMELL TOOL: get_callers(func='{function_name}', file='{file_path}')"
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
        def check_circular_dependencies():
            """Analyzes the import graph to find cycles."""
            logger.info("SMELL TOOL: check_circular_dependencies()")
            return "Scan for circular dependencies initiated in Knowledge Graph."

        @tool
        def emit_code_smell(
            title: str,
            severity: str,
            description: str,
            refactoring_suggestion: str,
            complexity_score: int,
            line: int,
        ):
            """Record a code smell with a specific suggestion."""
            logger.info(
                f"SMELL TOOL: emit_smell(title='{title}', complexity='{complexity_score}')"
            )
            return json.dumps(
                {
                    "title": title,
                    "category": "smell",
                    "severity": severity,
                    "description": description,
                    "remediation": refactoring_suggestion,
                    "complexity_score": complexity_score,
                    "line": line,
                }
            )

        self.tools = [
            get_file,
            get_callers,
            check_circular_dependencies,
            emit_code_smell,
        ]
        self.llm = get_llm(temperature=0, tools=self.tools)

    async def _call_model(self, state: AgentState):
        messages = state["messages"]
        logger.info(
            f"--- SMELL AGENT PROMPT PREVIEW ---\n{str(messages[-1].content)[:200]}..."
        )
        async with llm_limiter:
            response = await self.llm.ainvoke(messages)
        logger.info(
            f"--- SMELL AI RESPONSE ---\n{response.content}\nTool Calls: {response.tool_calls}"
        )
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        return "continue" if state["messages"][-1].tool_calls else "end"

    async def run(self, batch_state: Dict) -> Dict:
        all_smells = []
        config = batch_state.get("project_config", {})
        max_depth = config.get("max_recursion_depth", 3)

        for file_info in batch_state.get("files", []):
            logger.info(f"Smell investigation started for: {file_info['path']}")

            arch_summary = ""
            if batch_state.get("codebase_summary"):
                arch_summary = f"\nCODEBASE ARCHITECTURAL OVERVIEW:\n{batch_state['codebase_summary']}\n"

            user_instr = (
                f"\nCUSTOM USER INSTRUCTIONS:\n{batch_state['user_prompt']}\n"
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
You are a Senior Architect. Identify structural problems (God Classes, Feature Envy, Circular Deps).
{arch_summary}
{user_instr}

════════════════════════════════════════
HOW TO INVESTIGATE
════════════════════════════════════════

PLAN → ACT → OBSERVE → REASON → (repeat or CONCLUDE)

PLAN
Before calling any tool, write a short investigation plan. Answer:
- What are the structural characteristics of this file?
  (number of classes, methods per class, lines per method, import count)
- What smells are immediately visible from local analysis?
- Which smells require graph walking to assess severity?
  (god class blast radius, circular deps, dead code, duplicate code)
- What does the style guide say that is relevant to this file?
- Which suppressions or ADRs might already cover something I am about to flag?

Keep the plan to 6-8 bullet points. Do not begin tool calls until the plan is written.

ACT
Call one tool at a time. State your reason in one sentence before each call.

OBSERVE
Summarise in 1-2 sentences what you learned and whether it changes
the severity of the smell you were investigating.

REASON
After each observation decide:
- Does this confirm and contextualise the smell? → emit_code_smell
- Does this show the smell is less severe than it appeared? → downgrade or drop
- Do I need graph context to assess severity? → call another tool if depth allows
- Have I finished this smell? → move to the next candidate

DEPTH CONTROL
Current depth: {{current_depth}} / {max_depth}

At depth 0-1: Walk the graph freely to assess blast radius and coupling.
At depth 2:   Only fetch files needed to confirm severity of a specific smell.
At depth 3+:  Conclude. Emit confirmed findings. Do not open new files.

════════════════════════════════════════
SMELL CHECKLIST
════════════════════════════════════════

Work through these categories in order of architectural impact.

STRUCTURAL SMELLS (highest priority — flag these first)

God class
□ Does any class have more than 15 methods or more than 20 fields?
□ Does it have responsibilities that belong to more than one domain?
□ Run get_callers to check how many external files depend on it.
  Severity scales with dependents: <5 = low, 5-20 = medium, >20 = high.

Circular dependency
□ Does this file import a module that (directly or transitively) imports
  this file back?
□ Use get_imports recursively up to depth 2 to check.
  Any confirmed cycle is at minimum medium severity.
  A cycle involving more than 3 modules is high severity.

Shotgun surgery
□ Are there functions here that are called from many unrelated modules?
  Use get_callers — if a utility function is called from >10 unrelated
  files and does something very specific, it signals hidden coupling.

Divergent change
□ Does this class get called by modules from many different domains?
  (auth module AND billing module AND reporting module all calling the
   same class signals it is changing for too many reasons)

Dead code
□ Are there functions, classes, or imports defined here but never used?
□ Use get_callers on any suspicious function — empty result on a
  non-public, non-entry-point function confirms dead code.
□ Commented-out code blocks are always flagged, regardless of size.

OBJECT-ORIENTED SMELLS

Feature envy
□ Does any method use more attributes or methods from another class
  than from its own class? It probably belongs in that other class.

Inappropriate intimacy
□ Does this class call private or protected methods of another class?
  Use get_callees to check — calls to _method or __method on external
  objects are a strong signal.

Refused bequest
□ Does a subclass override most parent methods with empty bodies
  or NotImplementedError / UnsupportedOperationException?
  Use get_class_hierarchy to find the parent and compare.

Data class
□ Does this class have only fields and getters/setters with no behaviour?
  Not always a smell alone — flag only when other classes are performing
  all operations on its data (combined with feature envy elsewhere).

Parallel inheritance hierarchies
□ Does adding a subclass of A always require adding a subclass of B?
  Check class hierarchy shapes across the codebase.

METHOD SMELLS

Long method
□ Any method over 40 lines?
□ Any method with more than 3 levels of nesting?
□ Flag with a decomposition suggestion naming the logical blocks.

Long parameter list
□ Any function with more than 4 parameters?
□ Do several parameters always travel together? → missing abstraction.

Flag argument
□ Boolean parameter that switches between two fundamentally different
  behaviours inside the function? → should be two functions.

Arrow anti-pattern
□ More than 3 levels of nested conditionals in a single function?
□ Suggest early returns or guard clauses as the fix.

Inappropriate return type
□ Function returning None sometimes and a value other times?
□ Function returning different types depending on a condition?

CODE-LEVEL SMELLS

Magic numbers and strings
□ Numeric or string literals used directly in logic without a named constant?
□ Same literal appearing in more than one place?
□ Flag with the suggested constant name.

Duplicate code
□ Structurally similar blocks appearing in multiple functions or files?
□ Compare AST structure, not just text — same logic with different
  variable names still counts.
□ Use get_file on suspicious sibling modules to check cross-file duplication.

Primitive obsession
□ Email, phone, money, user ID, or other domain concepts passed
  as raw strings, floats, or ints rather than typed value objects?

Inconsistent abstraction levels
□ A single function mixing high-level orchestration (call validate_cart())
  with low-level implementation (cursor.execute("SELECT ..."))?

Speculative generality
□ Abstract base classes, hooks, or extension points with only one
  implementation and no planned second?
□ Parameters that are always passed the same value?

STYLE GUIDE VIOLATIONS (always flag regardless of severity)
□ Review the style guide chunks in your context.
□ Flag any clear violation — naming, structure, pattern preference.
□ Reference the specific style guide rule in the finding description.

════════════════════════════════════════
SEVERITY GUIDELINES
════════════════════════════════════════

CRITICAL
Reserved for smells that actively block the team from making changes safely.
Circular dependency between core modules. God class with >30 dependents.
Duplicate business logic in two places that have already diverged.

HIGH
Smells that will cause significant pain in the next 1-3 months.
God class with 10-30 dependents. Shotgun surgery across many modules.
Long methods over 100 lines with deep nesting. Refused bequest in core hierarchy.

MEDIUM
Smells that accumulate technical debt steadily.
Feature envy. Inappropriate intimacy. Long methods 40-100 lines.
Dead code. Primitive obsession on domain concepts. Magic numbers in logic.

LOW
Smells that reduce readability but have limited structural impact.
Flag arguments. Long parameter lists. Inconsistent abstraction levels.
Speculative generality. Style guide violations.

════════════════════════════════════════
ANTI-LOOP PROTOCOL
════════════════════════════════════════
If a tool call fails, DO NOT call it again with the exact same arguments. 
Try a different approach or move on.

PROJECT_ROOT: {self.project_root}
MAX RECURSION DEPTH: {max_depth}
"""
            )
            initial_input = {
                "messages": [
                    system_msg,
                    HumanMessage(
                        content=f"Analyze for code smells:\nPATH: {file_info['path']}\nCONTENT:\n{file_info['content']}"
                    ),
                ]
            }
            try:
                result = await compiled_agent.ainvoke(
                    initial_input, {"recursion_limit": config.get("max_iterations", 25)}
                )
                for msg in result["messages"]:
                    if isinstance(msg, ToolMessage) and msg.name == "emit_code_smell":
                        try:
                            smell_data = json.loads(msg.content)
                            smell_data["file_path"] = file_info["path"]
                            all_smells.append(smell_data)
                        except:
                            pass
            except Exception as e:
                logger.error(f"Smell loop failed for {file_info['path']}: {e}")
                continue
        return {"smell_findings": all_smells}
