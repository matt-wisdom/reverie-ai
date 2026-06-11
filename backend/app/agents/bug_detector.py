import json
import os
import re
import glob
from typing import List, Dict
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from ..graph.state import AgentState
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.config import GEMINI_MODEL_TYPE, GEMINI_API_KEY, REVERIE_MAX_ITERATIONS
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class BugDetectorAgent:
    def __init__(self, tag: str, project_dir: str, project_root: str):
        self.tag = tag
        self.project_dir = project_dir
        self.project_root = project_root
        self.ladybug = LadybugClient(db_path=f"{project_dir}/graph_db")
        self.chroma = ChromaClient(path=f"{project_dir}/vector_db")
        
        # Define tools inside init to capture clients in closure
        @tool
        def get_file(path: str):
            """Fetch the full content of any file in the codebase."""
            logger.info(f"TOOL CALL: get_file(path='{path}')")
            try:
                target_path = path if os.path.isabs(path) else os.path.join(self.project_root, path)
                with open(target_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file: {e}"

        @tool
        def find_files(filename_query: str):
            """Find full paths for files matching a filename or pattern (e.g. 'memory_manager.py')."""
            logger.info(f"TOOL CALL: find_files(query='{filename_query}')")
            results = []
            search_pattern = os.path.join(self.project_root, "**", f"*{filename_query}*")
            for filepath in glob.glob(search_pattern, recursive=True):
                if os.path.isfile(filepath):
                    results.append(filepath)
            return json.dumps(results[:10])

        @tool
        def get_callers(function_name: str, file_path: str):
            """Find all functions that call this function across the codebase."""
            logger.info(f"TOOL CALL: get_callers(func='{function_name}', file='{file_path}')")
            query = "MATCH (c:Function {id: $id})<-[:CALLS]-(caller:Function) RETURN caller.name, caller.file"
            res = self.ladybug.execute(query, {"id": f"{file_path}:{function_name}"})
            if res.has_next():
                df = res.get_as_df().replace({float('nan'): None})
                return json.dumps(df.to_dict(orient="records"))
            return "[]"

        @tool
        def get_callees(function_name: str, file_path: str):
            """Find all functions called by this function."""
            logger.info(f"TOOL CALL: get_callees(func='{function_name}', file='{file_path}')")
            query = "MATCH (c:Function {id: $id})-[:CALLS]->(callee:Function) RETURN callee.name, callee.file"
            res = self.ladybug.execute(query, {"id": f"{file_path}:{function_name}"})
            if res.has_next():
                df = res.get_as_df().replace({float('nan'): None})
                return json.dumps(df.to_dict(orient="records"))
            return "[]"

        @tool
        def get_imports(file_path: str):
            """List all resolved imports and architectural hints for this file."""
            logger.info(f"TOOL CALL: get_imports(file='{file_path}')")
            query = "MATCH (m:Module {path: $path})-[:DIR_TO_MODULE]-(d:Directory) RETURN d.summary, d.context"
            res = self.ladybug.execute(query, {"path": file_path})
            if res.has_next():
                df = res.get_as_df().replace({float('nan'): None})
                return json.dumps(df.to_dict(orient="records"))
            return "[]"

        @tool
        def query_memory(question: str):
            """Semantic search against project memory and documentation (Hybrid RAG)."""
            logger.info(f"TOOL CALL: query_memory(q='{question}')")
            results = self.chroma.query([question], n_results=3)
            return json.dumps(results)

        @tool
        def emit_finding(title: str, severity: str, description: str, line: int):
            """Record a confirmed bug finding."""
            logger.info(f"TOOL CALL: emit_finding(title='{title}', severity='{severity}')")
            return json.dumps({
                "title": title,
                "category": "bug",
                "severity": severity,
                "description": description,
                "line": line
            })

        self.tools = [get_file, find_files, get_callers, get_callees, get_imports, query_memory, emit_finding]
        
        self.llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL_TYPE,
            google_api_key=GEMINI_API_KEY,
            temperature=0
        ).bind_tools(self.tools)

    def _call_model(self, state: AgentState):
        messages = state["messages"]
        last_msg_content = messages[-1].content
        prompt_preview = "\n".join(str(last_msg_content).split("\n")[:5])
        logger.info(f"--- AGENT PROMPT PREVIEW ---\n{prompt_preview}\n...")
        
        logger.info("Bug Detector thinking...")
        response = self.llm.invoke(messages)
        logger.info(f"--- AI RESPONSE ---\n{response.content}\nTool Calls: {response.tool_calls}")
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if not last_message.tool_calls:
            return "end"
        return "continue"

    async def run(self, batch_state: Dict) -> Dict:
        """Executes the ReAct flow for a batch of files."""
        all_bug_findings = []
        config_data = batch_state.get("project_config", {})
        max_depth = config_data.get("max_recursion_depth", 3)
        recursion_limit = config_data.get("max_iterations", 25)
        
        for file_info in batch_state.get("files", []):
            logger.info(f"ReAct Investigation started for: {file_info['path']} (max_depth: {max_depth}, recursion_limit: {recursion_limit})")
            
            # PUSH MODEL: Fetch relevant context documents before starting
            project_context = await self._get_relevant_context(file_info)
            
            workflow = StateGraph(AgentState)
            workflow.add_node("agent", self._call_model)
            workflow.add_node("tools", ToolNode(self.tools))
            workflow.set_entry_point("agent")
            workflow.add_conditional_edges("agent", self._should_continue, {"continue": "tools", "end": END})
            workflow.add_edge("tools", "agent")
            compiled_agent = workflow.compile()
            
            system_msg = SystemMessage(content=f"""
You are a Senior Bug Detector. 
Investigate the following file and its dependencies to find critical logic bugs.
PROJECT_ROOT: {self.project_root}
MAX RECURSION DEPTH: {max_depth} (Each tool call that reads a new file increments depth).

PROJECT-SPECIFIC RULES & CONTEXT:
{project_context}

PLANNING STEPS:
1. Understand file structure and check if it follows the PROJECT-SPECIFIC RULES above.
2. Trace data flow from inputs to sinks.
3. Check cross-file dependencies if suspicious.
4. Conclude only when enough evidence is gathered.
""")
            
            initial_input = {
                "messages": [system_msg, HumanMessage(content=f"Investigate this file for bugs:\nPATH: {file_info['path']}\nCONTENT:\n{file_info['content']}")]
            }
            
            try:
                result = await compiled_agent.ainvoke(initial_input, {"recursion_limit": recursion_limit})
                for msg in result["messages"]:
                    if isinstance(msg, ToolMessage) and msg.name == "emit_finding":
                        try:
                            finding_data = json.loads(msg.content)
                            finding_data["file_path"] = file_info["path"]
                            all_bug_findings.append(finding_data)
                        except:
                            pass
            except Exception as e:
                logger.error(f"ReAct investigation for {file_info['path']} hit a limit or failed: {e}")
                continue
        
        return {"bug_findings": all_bug_findings}

    async def _get_relevant_context(self, file_info: Dict) -> str:
        """Proactively retrieves documentation related to the current file."""
        query_text = f"Architecture, security rules, and coding standards for {file_info['path']}"
        try:
            # Hybrid search in ChromaDB
            results = self.chroma.query([query_text], n_results=3)
            
            # Filter results to only include those from actual docs (ContextDoc chunks have doc_id)
            doc_chunks = []
            for r in results:
                meta = r.get("metadata", {})
                if "doc_id" in meta:
                    breadcrumb = meta.get("breadcrumb", "Unknown Section")
                    doc_chunks.append(f"[{breadcrumb}]: {r['document']}")
            
            if not doc_chunks:
                return "No specific project rules found for this file."
                
            context_block = "\n\n".join(doc_chunks)
            return f"Applicable Project Guidelines:\n{context_block}"
        except Exception as e:
            logger.warning(f"Failed to fetch proactive context: {e}")
            return "Could not retrieve project-specific rules."
