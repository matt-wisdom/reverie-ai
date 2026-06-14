import os
import re
import uuid
import asyncio
import glob
import hashlib
from datetime import datetime
from typing import List, Dict, Set, Optional

# Tree-sitter grammars
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
import tree_sitter_go as tsgo
import tree_sitter_rust as tsrust
import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
import tree_sitter_bash as tsbash
import tree_sitter_html as tshtml
import tree_sitter_sql as tssql

from tree_sitter import Query, QueryCursor, Language, Parser
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.llm_provider import get_llm
from ..core.logging_config import get_logger
from ..core.config import llm_limiter, get_project_dir

logger = get_logger(__name__)

# Initialize Languages
LANGUAGES = {
    "py": Language(tspython.language()),
    "js": Language(tsjs.language()),
    "ts": Language(tsts.language_typescript()),
    "tsx": Language(tsts.language_tsx()),
    "go": Language(tsgo.language()),
    "rs": Language(tsrust.language()),
    "c": Language(tsc.language()),
    "cpp": Language(tscpp.language()),
    "sh": Language(tsbash.language()),
    "html": Language(tshtml.language()),
    "sql": Language(tssql.language()),
}

# Supported file extensions for full AST analysis
AST_SUPPORTED_EXTS = set(LANGUAGES.keys()) | {"vue", "h", "hpp"}

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
        # Initialize parsers
        self.parsers = {ext: Parser(lang) for ext, lang in LANGUAGES.items()}
        # Map header files
        self.parsers["h"] = self.parsers["c"]
        self.parsers["hpp"] = self.parsers["cpp"]
        self.parsers["vue"] = self.parsers["js"]

        self.ladybug_client = LadybugClient(db_path=self.project_dir / "graph_db")
        self.chroma_client = ChromaClient(path=self.project_dir / "vector_db")

        # Initialize LLM for summarization
        self.llm = get_llm(temperature=0)
        self.nodes_written = 0

    async def process_codebase(
        self,
        root_path: str,
        project_name: str = "Unknown",
        force: bool = False,
        user_prompt: Optional[str] = None,
    ):
        """Main entry point for repo repo ingestion."""
        self.user_prompt = user_prompt
        logger.info(
            f"Starting codebase ingestion for project {self.tag}: {root_path} (Force: {force})"
        )

        self.ladybug_client.init_schema()
        self.nodes_written = 0

        # 1. Initialize Project Node
        now = datetime.utcnow().isoformat()
        logger.info(f"GRAPH: Merging Project node: {self.tag} ({project_name})")
        self.ladybug_client.execute(
            "MERGE (p:Project {id: $id}) SET p.name = $name, p.created_at = $now, p.last_reviewed_at = $now",
            {"id": self.tag, "name": project_name, "now": now},
        )
        self.nodes_written += 1

        # Supported source extensions for full AST analysis
        AST_EXTS = (
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".vue",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".sh",
            ".sql",
        )
        # Supported config files for semantic fallback chunking
        CONFIG_EXTS = (
            ".dockerfile",
            ".terraform",
            ".tf",
            ".yaml",
            ".yml",
            ".json",
            ".toml",
        )

        total_folders = 0
        total_files = 0

        for root, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if d not in self.ignore_list]
            total_folders += 1

            folder_context = self._get_folder_context(root, files)
            # Re-summarize if force is True
            summary = await self._generate_folder_summary(
                root, files, folder_context, force=force
            )
            self._store_folder_metadata(root, summary, folder_context)

            relevant_files = []
            for file in files:
                if file == ".reverie.yaml":
                    continue
                file_path = os.path.join(root, file)
                ext = f".{file.split('.')[-1].lower()}" if "." in file else ""
                is_ast = file.lower().endswith(AST_EXTS)
                is_config = (
                    file.lower().endswith(CONFIG_EXTS) or file.lower() == "dockerfile"
                )

                if is_ast or is_config:
                    lang_type = ext.replace(".", "") if ext else "dockerfile"
                    relevant_files.append((file_path, lang_type))

            if relevant_files:
                logger.info(
                    f"Folder: {root} - Processing {len(relevant_files)} files..."
                )
                for i, (file_path, lang_type) in enumerate(relevant_files):
                    total_files += 1
                    if i % 10 == 0 and i > 0:
                        logger.info(
                            f"  > Progress in {os.path.basename(root)}: {i}/{len(relevant_files)}"
                        )
                    await self._process_file(file_path, lang_type, force=force)

        # 4. Generate and Store high-level Project Summary
        await self._generate_and_store_project_summary(project_name)

        logger.info(
            f"Finished codebase ingestion for {self.tag}. Folders: {total_folders}, Files: {total_files}, Total Graph Nodes Written: {self.nodes_written}"
        )

    async def _generate_and_store_project_summary(self, project_name: str):
        """Synthesizes all directory data into a single project-level architectural summary."""
        logger.info(f"GRAPH: Synthesizing final project summary for {self.tag}...")
        try:
            res = self.ladybug_client.execute(
                "MATCH (d:Directory) RETURN d.path, d.summary"
            )
            summaries = []
            if res.has_next():
                df = res.get_as_df()
                for _, row in df.iterrows():
                    if row["d.summary"] != "Non-code directory.":
                        summaries.append(
                            f"Path: {row['d.path']}\nSummary: {row['d.summary']}"
                        )

            if not summaries:
                return

            all_context = "\n\n".join(summaries)
            user_instr = (
                f"\nCUSTOM USER INSTRUCTIONS:\n{self.user_prompt}\n"
                if self.user_prompt
                else ""
            )
            prompt = f"Provide a comprehensive, high-level architectural overview of the project '{project_name}' based on these directory summaries:\n\n{all_context}\n{user_instr}"

            async with llm_limiter:
                response = await self.llm.ainvoke(prompt)
                project_summary = response.content

            self.ladybug_client.execute(
                "MATCH (p:Project {id: $id}) SET p.summary = $summary",
                {"id": self.tag, "summary": project_summary},
            )
            logger.info("GRAPH: Project summary stored successfully.")
        except Exception as e:
            logger.warning(f"Failed to generate final project summary: {e}")

    def _get_folder_context(self, path: str, files: list[str]) -> str:
        """Finds and reads architecture hint files (e.g., GEMINI.md)."""
        context = ""
        for cfg in self.config_files:
            if cfg in files:
                logger.info(
                    f"Reading architectural context from: {os.path.join(path, cfg)}"
                )
                try:
                    with open(os.path.join(path, cfg), "r") as f:
                        context += f"\n--- {cfg} ---\n{f.read()}"
                except Exception as e:
                    logger.error(f"Error reading config file {cfg}: {e}")
        return context

    async def _generate_folder_summary(
        self, path: str, files: list[str], context: str, force: bool = False
    ) -> str:
        """Uses LLM to summarize the purpose of a folder."""
        if not any(
            f.endswith(
                (
                    ".py",
                    ".js",
                    ".ts",
                    ".tsx",
                    ".vue",
                    ".c",
                    ".cpp",
                    ".go",
                    ".rs",
                    ".h",
                    ".hpp",
                    ".sh",
                )
            )
            for f in files
        ):
            return "Non-code directory."

        # If not forcing, check if we already have a summary
        if not force:
            res = self.ladybug_client.execute(
                "MATCH (d:Directory {path: $path}) RETURN d.summary", {"path": path}
            )
            if res.has_next():
                df = res.get_as_df()
                if not df.empty:
                    existing = df.iloc[0]["d.summary"]
                    if (
                        existing
                        and existing != "Non-code directory."
                        and "Error generating summary" not in existing
                    ):
                        return existing

        logger.info(f"Requesting AI summary for folder: {path}...")
        user_instr = (
            f"\nCUSTOM USER INSTRUCTIONS:\n{self.user_prompt}\n"
            if self.user_prompt
            else ""
        )
        prompt = f"Summarize the purpose and architecture of the folder '{path}' based on these files: {files}. Context: {context}\n{user_instr}"
        try:
            async with llm_limiter:
                response = await self.llm.ainvoke(prompt)
                return response.content
        except Exception as e:
            logger.error(f"Error generating folder summary for {path}: {e}")
            return f"Error generating summary: {e}"

    def _store_folder_metadata(self, path: str, summary: str, context: str):
        """Stores folder insights in LadybugDB Knowledge Graph."""
        logger.info(f"GRAPH: Merging Directory node: {path}")
        self.ladybug_client.execute(
            "MERGE (d:Directory {path: $path}) SET d.summary = $summary, d.context = $context",
            {"path": path, "summary": summary, "context": context},
        )
        self.nodes_written += 1

    async def _process_file(self, file_path: str, ext: str, force: bool = False):
        """AST Extraction, Suppression Parsing & Semantic Chunking with incremental logic."""
        try:
            with open(file_path, "rb") as f:
                content = f.read()

            # Compute file hash
            file_hash = hashlib.sha256(content).hexdigest()

            # 1. Check if file has changed (skip if force=True)
            if not force:
                check_query = "MATCH (f:File {path: $path}) RETURN f.hash"
                res = self.ladybug_client.execute(check_query, {"path": file_path})
                if res.has_next():
                    df = res.get_as_df()
                    if not df.empty and df.iloc[0]["f.hash"] == file_hash:
                        logger.info(f"GRAPH: Skipping File (Unchanged): {file_path}")
                        return  # Skip re-processing

            # 2. Update/Create File Node
            now = datetime.utcnow().isoformat()
            logger.info(
                f"GRAPH: Merging File node: {file_path} (Lang: {ext}, Force: {force})"
            )
            self.ladybug_client.execute(
                "MERGE (f:File {path: $path}) SET f.language = $lang, f.last_seen = $now, f.hash = $hash",
                {"path": file_path, "lang": ext, "now": now, "hash": file_hash},
            )
            self.nodes_written += 1
            logger.debug(f"GRAPH: Linking File to Project: {file_path} -> {self.tag}")
            self.ladybug_client.execute(
                "MATCH (f:File {path: $path}), (p:Project {id: $pid}) MERGE (f)-[:FILE_IN_PROJ]->(p)",
                {"path": file_path, "pid": self.tag},
            )

            # 3. Parse Suppressions
            self._parse_suppressions(file_path, content)

            # Handle AST analysis
            parser = self.parsers.get(ext)
            if not parser and (ext == "vue" or ext == "html"):
                parser = self.parsers.get("js")

            if parser:
                tree = parser.parse(content)
                self._extract_symbols_to_kg(file_path, tree, content, ext)
                self._semantic_chunking_to_vector_db(file_path, tree, content)
            else:
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
            ignore_match = REVERIE_IGNORE_REGEX.search(line)
            if ignore_match:
                reason = ignore_match.group(1).strip()
                sid = f"suppress:{file_path}:{line_num}"
                logger.info(
                    f"GRAPH: Merging Suppression (ALL) for {file_path}:{line_num}"
                )
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
                self.nodes_written += 1
                continue

            suppress_match = REVERIE_SUPPRESS_REGEX.search(line)
            if suppress_match:
                rule_id = suppress_match.group(1).strip()
                reason = suppress_match.group(2).strip()
                sid = f"suppress:{file_path}:{line_num}:{rule_id}"
                logger.info(
                    f"GRAPH: Merging Suppression ({rule_id}) for {file_path}:{line_num}"
                )
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
                self.nodes_written += 1

    def _extract_symbols_to_kg(self, file_path: str, tree, content: bytes, ext: str):
        """Uses Tree-sitter to map symbols and function calls across languages."""
        lang_key = ext if ext in LANGUAGES else "js"
        lang = LANGUAGES.get(lang_key)

        logger.debug(f"GRAPH: Linking Module to Directory: {file_path}")
        self.ladybug_client.execute(
            "MATCH (d:Directory {path: $dir}) MERGE (m:Module {path: $path}) MERGE (d)-[:DIR_TO_MODULE]->(m)",
            {"dir": os.path.dirname(file_path), "path": file_path},
        )
        self.nodes_written += 1

        queries = {
            "py": """
                (import_from_statement module_name: (dotted_name) @import)
                (import_statement name: (dotted_name) @import)
                (class_definition name: (identifier) @class superclasses: (argument_list (identifier) @base)?)
                (function_definition name: (identifier) @func)
                (call function: (identifier) @call)
                (call function: (attribute attribute: (identifier) @call))
            """,
            "js": """
                (import_statement source: (string) @import)
                (class_declaration name: (identifier) @class heritage: (extends_clause value: (identifier) @base)?)
                (function_declaration name: (identifier) @func)
                (method_definition name: (property_identifier) @func)
                (call_expression function: (identifier) @call)
            """,
            "ts": """
                (class_declaration name: (identifier) @class)
                (function_declaration name: (identifier) @func)
                (method_definition name: (property_identifier) @func)
                (call_expression function: (identifier) @call)
            """,
            "go": """
                (type_declaration (type_spec name: (type_identifier) @class))
                (function_declaration name: (identifier) @func)
                (method_declaration name: (field_identifier) @func)
                (call_expression function: (identifier) @call)
                (call_expression function: (selector_expression field: (field_identifier) @call))
            """,
            "rs": """
                (struct_item name: (type_identifier) @class)
                (function_item name: (identifier) @func)
                (call_expression function: (identifier) @call)
                (call_expression function: (field_expression field: (field_identifier) @call))
            """,
            "c": """
                (struct_specifier name: (type_identifier) @class)
                (function_definition declarator: (function_declarator declarator: (identifier) @func))
                (call_expression function: (identifier) @call)
            """,
            "cpp": """
                (class_specifier name: (type_identifier) @class)
                (function_definition declarator: (function_declarator declarator: (identifier) @func))
                (call_expression function: (identifier) @call)
            """,
            "sh": """
                (function_definition name: (word) @func)
                (command name: (word) @call)
            """,
            "sql": """
                (create_table_statement name: (identifier) @class)
                (select_statement) @func
            """,
        }

        query_str = queries.get(lang_key)
        if not query_str:
            return

        query = Query(lang, query_str)
        cursor = QueryCursor(query)
        matches = cursor.matches(tree.root_node)

        current_func_name = None
        current_class_name = None
        for _, captures in matches:
            for tag, nodes in captures.items():
                for node in nodes:
                    try:
                        name = (
                            content[node.start_byte : node.end_byte]
                            .decode("utf-8", errors="ignore")
                            .strip("\"'")
                        )
                        if tag == "import":
                            self.ladybug_client.execute(
                                "MATCH (m1:Module {path: $file}) MERGE (m2:Module {path: $import_name}) MERGE (m1)-[:DEPENDS_ON]->(m2)",
                                {"file": file_path, "import_name": name},
                            )
                            # Dependency module is also a node
                            self.nodes_written += 1
                        elif tag == "class":
                            current_class_name = name
                            node_id = f"{file_path}:{name}"
                            logger.info(f"GRAPH: Merging Class node: {name}")
                            self.ladybug_client.execute(
                                "MATCH (m:Module {path: $file}) MERGE (c:Class {id: $id}) SET c.name = $name, c.file = $file MERGE (m)-[:MOD_TO_CLASS]->(c)",
                                {"id": node_id, "name": name, "file": file_path},
                            )
                            self.nodes_written += 1
                        elif tag == "base":
                            if current_class_name:
                                cid = f"{file_path}:{current_class_name}"
                                bid = f"external:{name}"
                                self.ladybug_client.execute(
                                    "MATCH (c1:Class {id: $id}) MERGE (c2:Class {id: $base_id}) SET c2.name = $base_name MERGE (c1)-[:INHERITS_FROM]->(c2)",
                                    {"id": cid, "base_id": bid, "base_name": name},
                                )
                                self.nodes_written += 1
                        elif tag == "func":
                            current_func_name = name
                            node_id = f"{file_path}:{name}"
                            is_entry = any(
                                k in name.lower()
                                for k in [
                                    "handler",
                                    "route",
                                    "controller",
                                    "endpoint",
                                    "view",
                                ]
                            )

                            # Generalized Entry Point Detection (Framework/Language Agnostic)
                            # Climb up the AST to catch decorators/macros wrapping the function
                            context_node = node
                            for _ in range(3):
                                if context_node.parent:
                                    context_node = context_node.parent

                            if context_node:
                                # Get the text from the start of the context down to the function name
                                context_text = (
                                    content[context_node.start_byte : node.end_byte]
                                    .decode("utf-8", errors="ignore")
                                    .lower()
                                )
                                routing_indicators = [
                                    "@get",
                                    "@post",
                                    "@put",
                                    "@delete",
                                    "@patch",
                                    "@route",
                                    "@api",
                                    "@endpoint",
                                    "#[get",
                                    "#[post",
                                    "#[put",
                                    "#[delete",
                                    "#[patch",
                                    "#[route",
                                    "router.get",
                                    "router.post",
                                    "router.put",
                                    "router.delete",
                                    "router.patch",
                                    "app.get",
                                    "app.post",
                                    "app.put",
                                    "app.delete",
                                    "app.patch",
                                    "http.handle",
                                ]
                                if any(
                                    ind in context_text for ind in routing_indicators
                                ):
                                    is_entry = True

                            logger.info(
                                f"GRAPH: Merging Function node: {name} (Entry: {is_entry})"
                            )
                            self.ladybug_client.execute(
                                "MATCH (m:Module {path: $file}) MERGE (f:Function {id: $id}) SET f.name = $name, f.file = $file, f.is_entry_point = $is_entry MERGE (m)-[:MOD_TO_FUNC]->(f)",
                                {
                                    "id": node_id,
                                    "name": name,
                                    "file": file_path,
                                    "is_entry": is_entry,
                                },
                            )
                            self.nodes_written += 1
                        elif tag == "call" and current_func_name:
                            caller_id = f"{file_path}:{current_func_name}"
                            self.ladybug_client.execute(
                                "MATCH (caller:Function {id: $caller_id}) "
                                "MERGE (callee:Function {id: $callee_name}) SET callee.name = $callee_name "
                                "MERGE (caller)-[:CALLS]->(callee)",
                                {"caller_id": caller_id, "callee_name": name},
                            )
                            # callee is a node
                            self.nodes_written += 1
                            # Sink detection
                            SINK_KEYWORDS = [
                                "execute",
                                "run",
                                "eval",
                                "pickle",
                                "render",
                                "redirect",
                                "system",
                                "popen",
                            ]
                            if any(k in name.lower() for k in SINK_KEYWORDS):
                                sink_id = (
                                    f"sink:{name}:{file_path}:{node.start_point[0]}"
                                )
                                self.ladybug_client.execute(
                                    "MATCH (f:Function {id: $func_id}) "
                                    "MERGE (s:Finding {finding_id: $sink_id}) SET s.title = $name, s.category = 'SINK' "
                                    "MERGE (f)-[:USES]->(s)",
                                    {
                                        "func_id": caller_id,
                                        "sink_id": sink_id,
                                        "name": f"Potential Sink: {name}",
                                    },
                                )
                                self.nodes_written += 1
                    except Exception as e:
                        logger.debug(
                            f"Failed to process symbol {tag} in {file_path}: {e}"
                        )
                        continue

    def _semantic_chunking_to_vector_db(self, file_path: str, tree, content: bytes):
        chunks, metadatas, ids = [], [], []

        def walk_for_chunks(node):
            if node.type in [
                "class_definition",
                "function_definition",
                "class_declaration",
                "function_declaration",
                "method_definition",
                "struct_item",
                "function_item",
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
            self._fallback_chunking(file_path, content)
        else:
            self.chroma_client.add_documents(chunks, metadatas, ids)

    def _fallback_chunking(self, file_path: str, content: bytes):
        text = content.decode("utf-8", errors="ignore")
        if not text.strip():
            return
        lines = text.splitlines()
        chunk_size = 50
        for i in range(0, len(lines), chunk_size):
            chunk = "\n".join(lines[i : i + chunk_size])
            if chunk.strip():
                self.chroma_client.add_documents(
                    [chunk],
                    [{"file_path": file_path, "type": "fb"}],
                    [f"{file_path}_fb_{i}"],
                )
