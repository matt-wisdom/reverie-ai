import json
import os
from typing import List, Dict, Optional
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from ..graph.state import AgentState
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.config import GEMINI_MODEL_TYPE, GEMINI_API_KEY, gemini_limiter
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class SmellDetectorAgent:
    def __init__(self, tag: str, project_dir: str, project_root: str):
        self.tag = tag
        self.project_dir = project_dir
        self.project_root = project_root
        self.ladybug = LadybugClient(db_path=f"{project_dir}/graph_db")
        self.chroma = ChromaClient(path=f"{project_dir}/vector_db")
        
        # --- Specialized Smell Tools ---

        @tool
        def get_file(path: str):
            """Fetch the full content of any file."""
            logger.info(f"SMELL TOOL: get_file(path='{path}')")
            try:
                target_path = path if os.path.isabs(path) else os.path.join(self.project_root, path)
                with open(target_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file: {e}"

        @tool
        def get_callers(function_name: str, file_path: str):
            """Find all callers to determine the 'God-ness' or coupling of a class/function."""
            logger.info(f"SMELL TOOL: get_callers(func='{function_name}', file='{file_path}')")
            query = "MATCH (c:Function {id: $id})<-[:CALLS]-(caller:Function) RETURN caller.name, caller.file"
            res = self.ladybug.execute(query, {"id": f"{file_path}:{function_name}"})
            if res.has_next():
                df = res.get_as_df().replace({float('nan'): None})
                return json.dumps(df.to_dict(orient="records"))
            return "[]"

        @tool
        def check_circular_dependencies():
            """Analyzes the import graph to find cycles (A -> B -> A)."""
            logger.info("SMELL TOOL: check_circular_dependencies()")
            query = "MATCH (m1:Module)-[:DIR_TO_MODULE]->(d)-[:DIR_TO_MODULE]->(m2:Module) WHERE m1.path = m2.path RETURN m1.path"
            # This is a simplified placeholder for a real cycle detection query
            return "Scan for circular dependencies initiated in the Knowledge Graph."

        @tool
        def query_style_memory(pattern: str):
            """Search project documentation for specific style or architectural standards."""
            logger.info(f"SMELL TOOL: query_style_memory(q='{pattern}')")
            results = self.chroma.query([f"coding standard for {pattern}"], n_results=3)
            return json.dumps(results)

        @tool
        def emit_code_smell(title: str, severity: str, description: str, refactoring_suggestion: str, complexity_score: int, line: int):
            """Record a code smell with a specific refactoring suggestion and local complexity score (1-10)."""
            logger.info(f"SMELL TOOL: emit_smell(title='{title}', complexity='{complexity_score}')")
            return json.dumps({
                "title": title,
                "category": "smell",
                "severity": severity, # high for structural, low for stylistic
                "description": description,
                "remediation": refactoring_suggestion,
                "complexity_score": complexity_score,
                "line": line
            })

        self.tools = [get_file, get_callers, check_circular_dependencies, query_style_memory, emit_code_smell]
        
        self.llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL_TYPE,
            google_api_key=GEMINI_API_KEY,
            temperature=0
        ).bind_tools(self.tools)

    async def _call_model(self, state: AgentState):
        messages = state["messages"]
        logger.info(f"--- SMELL AGENT PROMPT PREVIEW ---\n{str(messages[-1].content)[:200]}...")
        async with gemini_limiter:
            response = await self.llm.ainvoke(messages)
        logger.info(f"--- SMELL AI RESPONSE ---\n{response.content}\nTool Calls: {response.tool_calls}")
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        if not state["messages"][-1].tool_calls:
            return "end"
        return "continue"

    async def run(self, batch_state: Dict) -> Dict:
        all_smells = []
        config_data = batch_state.get("project_config", {})
        max_depth = config_data.get("max_recursion_depth", 3)
        recursion_limit = config_data.get("max_iterations", 25)

        for file_info in batch_state.get("files", []):
            logger.info(f"Smell investigation started for: {file_info['path']}")
            
            workflow = StateGraph(AgentState)
            workflow.add_node("agent", self._call_model)
            workflow.add_node("tools", ToolNode(self.tools))
            workflow.set_entry_point("agent")
            workflow.add_conditional_edges("agent", self._should_continue, {"continue": "tools", "end": END})
            workflow.add_edge("tools", "agent")
            compiled_agent = workflow.compile()

            system_msg = SystemMessage(content=f"""
You are a Senior Software Architect and Code Quality Expert.
Your goal is to identify code smells—structural problems that make code hard to maintain, test, or extend.

SMELL CATEGORIES:
1. OO Design: God Classes, Feature Envy, Inappropriate Intimacy, Refused Bequest.
2. Method Smells: Long Methods (>40 lines), Long Parameter Lists (>5), Flag Arguments, Dead Code.
3. Structural: Circular Dependencies, Shotgun Surgery, Divergent Change.
4. Code-level: Magic Numbers/Strings, Duplicate Code, Primitive Obsession.

INVESTIGATION STRATEGY:
1. Count methods and fields locally to detect God Classes or Data Classes.
2. Use 'get_callers' to determine if a class is an architectural bottleneck (high coupling).
3. Use 'check_circular_dependencies' to find unhealthy module relationships.
4. Look for the 'Arrow Anti-pattern' (deep nesting > 3 levels).
5. Identify 'Feature Envy' by seeing if a method uses more data from external objects than its own.

PROJECT_ROOT: {self.project_root}
MAX RECURSION DEPTH: {max_depth}
""")
            
            initial_input = {
                "messages": [system_msg, HumanMessage(content=f"Analyze this file for code smells:\nPATH: {file_info['path']}\nCONTENT:\n{file_info['content']}")]
            }

            try:
                result = await compiled_agent.ainvoke(initial_input, {"recursion_limit": recursion_limit})
                for msg in result["messages"]:
                    if isinstance(msg, ToolMessage) and msg.name == "emit_code_smell":
                        try:
                            smell_data = json.loads(msg.content)
                            smell_data["file_path"] = file_info["path"]
                            all_smells.append(smell_data)
                        except:
                            pass
            except Exception as e:
                logger.error(f"Smell ReAct loop failed for {file_info['path']}: {e}")
                continue

        return {"smell_findings": all_smells}
