import os
import re
import uuid
import asyncio
from datetime import datetime
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import QueryCursor, Language, Parser
import google.generativeai as genai
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.logging_config import get_logger
from ..core.config import (
    GEMINI_MODEL_TYPE,
    GEMINI_API_KEY,
    gemini_limiter,
    get_project_dir,
)

logger = get_logger(__name__)

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL_TYPE)

# Initialize Languages
LANGUAGES = {
    "py": Language(tspython.language()),
    "js": Language(tsjs.language()),
    "ts": Language(tsts.language_typescript()),
    "tsx": Language(tsts.language_tsx()),
}

# Regex for suppression comments
REVERIE_IGNORE_REGEX = re.compile(r"reverie:\s*ignore\s*-\s*(.*)", re.IGNORECASE)
REVERIE_SUPPRESS_REGEX = re.compile(
    r"reverie:\s*suppress\s*([a-zA-Z0-9_-]+)\s*-\s*(.*)", re.IGNORECASE
)


class IngestionPipeline:
    def __init__(self, tag: str, skip_dirs: list[str] = None):
        self.tag = tag
        self.project_dir = get_project_dir(tag)
        self.ignore_list = (
            set(skip_dirs)
            if skip_dirs
            else {
                ".git",
                "node_modules",
                "__pycache__",
                "venv",
                ".venv",
                "dist",
                "build",
                ".reverie.yaml",
                ".pytest_cache",
                "chroma_data",
                "chroma_db",
                "dataset",
                ".idea",
                ".vscode",
            }
        )
        self.ignore_list.add(".reverie.yaml")

        self.config_files = {"CLAUDE.md", "REVERIE.md", "AGENTS.md", "GEMINI.md"}
        self.parsers = {ext: Parser(lang) for ext, lang in LANGUAGES.items()}

        self.ladybug_client = LadybugClient(db_path=self.project_dir / "graph_db")
        self.chroma_client = ChromaClient(path=self.project_dir / "vector_db")

    async def process_codebase(self, root_path: str, project_name: str = "Unknown"):
        """Main entry point for repo ingestion."""
        logger.info(f"Starting codebase ingestion for project {self.tag}: {root_path}")
        self.ladybug_client.init_schema()

        # 1. Initialize Project Node
        now = datetime.utcnow().isoformat()
        self.ladybug_client.execute(
            "MERGE (p:Project {id: $id}) SET p.name = $name, p.created_at = $now, p.last_reviewed_at = $now",
            {"id": self.tag, "name": project_name, "now": now},
        )

        for root, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if d not in self.ignore_list]

            folder_context = self._get_folder_context(root, files)
            summary = await self._generate_folder_summary(root, files, folder_context)
            self._store_folder_metadata(root, summary, folder_context)

            for file in files:
                ext = file.split(".")[-1]
                if ext in self.parsers or ext == "vue":
                    file_path = os.path.join(root, file)
                    logger.debug(f"Processing file: {file_path}")
                    await self._process_file(file_path, ext)
        logger.info(f"Finished codebase ingestion for project {self.tag}")

    def _get_folder_context(self, path: str, files: list[str]) -> str:
        """Finds and reads architecture hint files (e.g., GEMINI.md)."""
        context = ""
        for cfg in self.config_files:
            if cfg in files:
                logger.debug(f"Found architecture hint file: {cfg} in {path}")
                try:
                    with open(os.path.join(path, cfg), "r") as f:
                        context += f"\n--- {cfg} ---\n{f.read()}"
                except Exception as e:
                    logger.error(f"Error reading config file {cfg}: {e}")
        return context

    async def _generate_folder_summary(
        self, path: str, files: list[str], context: str
    ) -> str:
        """Uses Gemini to summarize the purpose of a folder."""
        logger.info(f"Generating AI summary for folder: {path}")
        prompt = f"Summarize the purpose and architecture of the folder '{path}' based on these files: {files}. Context: {context}"
        try:
            async with gemini_limiter:
                response = await model.generate_content_async(prompt)
                return response.text
        except Exception as e:
            logger.error(f"Error generating folder summary for {path}: {e}")
            return f"Error generating summary: {e}"

    def _store_folder_metadata(self, path: str, summary: str, context: str):
        """Stores folder insights in LadybugDB Knowledge Graph."""
        logger.debug(f"Storing folder metadata in KG for: {path}")
        self.ladybug_client.execute(
            "MERGE (d:Directory {path: $path}) SET d.summary = $summary, d.context = $context",
            {"path": path, "summary": summary, "context": context},
        )

    async def _process_file(self, file_path: str, ext: str):
        """AST Extraction, Suppression Parsing & Semantic Chunking."""
        try:
            with open(file_path, "rb") as f:
                content = f.read()

            # 2. Update File Node
            now = datetime.utcnow().isoformat()
            self.ladybug_client.execute(
                "MERGE (f:File {path: $path}) SET f.language = $lang, f.last_seen = $now",
                {"path": file_path, "lang": ext, "now": now},
            )
            self.ladybug_client.execute(
                "MATCH (f:File {path: $path}), (p:Project {id: $pid}) MERGE (f)-[:FILE_IN_PROJ]->(p)",
                {"path": file_path, "pid": self.tag},
            )

            # 3. Parse Suppressions
            self._parse_suppressions(file_path, content)

            parser = self.parsers.get(ext)
            if not parser and ext == "vue":
                parser = self.parsers.get("js")

            if parser:
                tree = parser.parse(content)
                self._extract_symbols_to_kg(file_path, tree, content, ext)
                self._semantic_chunking_to_vector_db(file_path, tree, content)
            else:
                logger.warning(
                    f"No AST parser found for {ext}. Using fallback chunking for {file_path}"
                )
                self._fallback_chunking(file_path, content)
        except Exception as e:
            logger.error(f"Failed to process file {file_path}: {e}")

    def _parse_suppressions(self, file_path: str, content: bytes):
        """Find reverie:ignore and reverie:suppress in comments."""
        text = content.decode("utf-8", errors="ignore")
        lines = text.splitlines()
        now = datetime.utcnow().isoformat()

        for i, line in enumerate(lines):
            line_num = i + 1

            # Match # reverie: ignore - reason
            ignore_match = REVERIE_IGNORE_REGEX.search(line)
            if ignore_match:
                reason = ignore_match.group(1).strip()
                sid = f"suppress:{file_path}:{line_num}"
                self.ladybug_client.execute(
                    "MERGE (s:Suppression {suppression_id: $sid}) SET s.rule_id = 'ALL', s.reason = $reason, s.file_path = $file, s.line = $line, s.created_at = $now",
                    {
                        "sid": sid,
                        "reason": reason,
                        "file": file_path,
                        "line": line_num,
                        "now": now,
                    },
                )
                continue

            # Match // reverie: suppress rule-id - reason
            suppress_match = REVERIE_SUPPRESS_REGEX.search(line)
            if suppress_match:
                rule_id = suppress_match.group(1).strip()
                reason = suppress_match.group(2).strip()
                sid = f"suppress:{file_path}:{line_num}:{rule_id}"
                self.ladybug_client.execute(
                    "MERGE (s:Suppression {suppression_id: $sid}) SET s.rule_id = $rule, s.reason = $reason, s.file_path = $file, s.line = $line, s.created_at = $now",
                    {
                        "sid": sid,
                        "rule": rule_id,
                        "reason": reason,
                        "file": file_path,
                        "line": line_num,
                        "now": now,
                    },
                )

    def _extract_symbols_to_kg(self, file_path: str, tree, content: bytes, ext: str):
        """Uses Tree-sitter to map symbols and function calls across languages."""
        lang = LANGUAGES.get(ext) or LANGUAGES.get("js")
        from tree_sitter import Query, QueryCursor

        # 1. Create Module for the file and link to Directory
        self.ladybug_client.execute(
            "MATCH (d:Directory {path: $dir}) "
            "MERGE (m:Module {path: $path}) "
            "MERGE (d)-[:DIR_TO_MODULE]->(m)",
            {"dir": os.path.dirname(file_path), "path": file_path},
        )

        # Language-specific queries for symbols AND calls
        queries = {
            "py": """
                (class_definition name: (identifier) @class)
                (function_definition name: (identifier) @func)
                (call function: (identifier) @call)
                (call function: (attribute attribute: (identifier) @call))
            """,
            "js": """
                (class_declaration name: (identifier) @class)
                (function_declaration name: (identifier) @func)
                (method_definition name: (property_identifier) @func)
                (call_expression function: (identifier) @call)
                (call_expression function: (member_expression property: (property_identifier) @call))
            """,
            "ts": """
                (class_declaration name: (identifier) @class)
                (function_declaration name: (identifier) @func)
                (method_definition name: (property_identifier) @func)
                (call_expression function: (identifier) @call)
                (call_expression function: (member_expression property: (property_identifier) @call))
            """,
            "tsx": """
                (class_declaration name: (identifier) @class)
                (function_declaration name: (identifier) @func)
                (method_definition name: (property_identifier) @func)
                (call_expression function: (identifier) @call)
                (call_expression function: (member_expression property: (property_identifier) @call))
            """,
            "vue": """
                (class_declaration name: (identifier) @class)
                (function_declaration name: (identifier) @func)
                (method_definition name: (property_identifier) @func)
                (call_expression function: (identifier) @call)
            """,
        }

        query_str = queries.get(ext, queries["js"])
        query = Query(lang, query_str)
        cursor = QueryCursor(query)
        matches = cursor.matches(tree.root_node)

        current_func_name = None
        for _, captures in matches:
            for tag, nodes in captures.items():
                for node in nodes:
                    name = content[node.start_byte : node.end_byte].decode(
                        "utf-8", errors="ignore"
                    )

                    if tag == "class":
                        node_id = f"{file_path}:{name}"
                        self.ladybug_client.execute(
                            "MATCH (m:Module {path: $file}) MERGE (c:Class {id: $id}) SET c.name = $name, c.file = $file MERGE (m)-[:MOD_TO_CLASS]->(c)",
                            {"id": node_id, "name": name, "file": file_path},
                        )
                    elif tag == "func":
                        current_func_name = name
                        node_id = f"{file_path}:{name}"
                        self.ladybug_client.execute(
                            "MATCH (m:Module {path: $file}) MERGE (f:Function {id: $id}) SET f.name = $name, f.file = $file MERGE (m)-[:MOD_TO_FUNC]->(f)",
                            {"id": node_id, "name": name, "file": file_path},
                        )
                    elif tag == "call" and current_func_name:
                        caller_id = f"{file_path}:{current_func_name}"
                        self.ladybug_client.execute(
                            "MATCH (caller:Function {id: $caller_id}) "
                            "MERGE (callee:Function {id: $callee_name}) SET callee.name = $callee_name "
                            "MERGE (caller)-[:CALLS]->(callee)",
                            {"caller_id": caller_id, "callee_name": name},
                        )

    def _semantic_chunking_to_vector_db(self, file_path: str, tree, content: bytes):
        chunks, metadatas, ids = [], [], []

        def walk_for_chunks(node):
            if node.type in [
                "class_definition",
                "function_definition",
                "class_declaration",
                "function_declaration",
                "method_definition",
            ]:
                chunk_text = content[node.start_byte : node.end_byte].decode(
                    "utf-8", errors="ignore"
                )
                if len(chunk_text.strip()) > 20:
                    chunks.append(chunk_text)
                    metadatas.append({"file_path": file_path, "type": node.type})
                    ids.append(f"{file_path}_{node.start_byte}")

            for child in node.children:
                walk_for_chunks(child)

        walk_for_chunks(tree.root_node)

        if not chunks:
            text = content.decode("utf-8", errors="ignore")
            if text.strip():
                chunks.append(text)
                metadatas.append({"file_path": file_path, "type": "full_file"})
                ids.append(f"{file_path}_full")

        if chunks:
            self.chroma_client.add_documents(chunks, metadatas, ids)

    def _fallback_chunking(self, file_path: str, content: bytes):
        """Simple line-based chunking for files where AST failed."""
        text = content.decode("utf-8", errors="ignore")
        lines = text.split("\n")
        chunk_size = 50
        for i in range(0, len(lines), chunk_size):
            chunk = "\n".join(lines[i : i + chunk_size])
            self.chroma_client.add_documents(
                [chunk],
                [{"file_path": file_path, "type": "fallback"}],
                [f"{file_path}_fb_{i}"],
            )
