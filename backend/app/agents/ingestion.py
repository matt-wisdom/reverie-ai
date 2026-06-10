import os
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import QueryCursor

from tree_sitter import Language, Parser
import google.generativeai as genai
from ..db.ladybug_db import ladybug_client
from ..vector_store.chroma_client import chroma_client
from ..core.logging_config import get_logger

logger = get_logger(__name__)

# Initialize Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize Languages
LANGUAGES = {
    "py": Language(tspython.language()),
    "js": Language(tsjs.language()),
    "ts": Language(tsts.language_typescript()),
    "tsx": Language(tsts.language_tsx()),
}

class IngestionPipeline:
    def __init__(self):
        self.ignore_list = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build"}
        self.config_files = {"CLAUDE.md", "REVERIE.md", "AGENTS.md", "GEMINI.md"}
        self.parsers = {ext: Parser(lang) for ext, lang in LANGUAGES.items()}

    async def process_codebase(self, root_path: str):
        """Main entry point for repo ingestion."""
        logger.info(f"Starting codebase ingestion for: {root_path}")
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
        logger.info(f"Finished codebase ingestion for: {root_path}")

    def _get_folder_context(self, path: str, files: list[str]) -> str:
        context = ""
        for cfg in self.config_files:
            if cfg in files:
                logger.debug(f"Found architecture hint file: {cfg} in {path}")
                with open(os.path.join(path, cfg), "r") as f:
                    context += f"\n--- {cfg} ---\n{f.read()}"
        return context

    async def _generate_folder_summary(self, path: str, files: list[str], context: str) -> str:
        logger.info(f"Generating AI summary for folder: {path}")
        prompt = f"Summarize the purpose and architecture of the folder '{path}' based on these files: {files}. Context: {context}"
        try:
            response = await model.generate_content_async(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Error generating folder summary for {path}: {e}")
            return f"Error generating summary: {e}"

    def _store_folder_metadata(self, path: str, summary: str, context: str):
        logger.debug(f"Storing folder metadata in KG for: {path}")
        ladybug_client.execute(
            "MERGE (d:Directory {path: $path}) SET d.summary = $summary, d.context = $context",
            {"path": path, "summary": summary, "context": context}
        )

    async def _process_file(self, file_path: str, ext: str):
        """AST Extraction & Semantic Chunking."""
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            
            parser = self.parsers.get(ext)
            if not parser and ext == "vue":
                parser = self.parsers.get("js")
                
            if parser:
                tree = parser.parse(content)
                self._extract_symbols_to_kg(file_path, tree, content, ext)
                self._semantic_chunking_to_vector_db(file_path, tree, content)
            else:
                logger.warning(f"No AST parser found for {ext}. Using fallback chunking for {file_path}")
                self._fallback_chunking(file_path, content)
        except Exception as e:
            logger.error(f"Failed to process file {file_path}: {e}")

    def _extract_symbols_to_kg(self, file_path: str, tree, content: bytes, ext: str):
        """Uses Tree-sitter to map symbols and function calls across languages."""
        lang = LANGUAGES.get(ext) or LANGUAGES.get("js")
        from tree_sitter import Query, QueryCursor

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
            """
        }
        
        query_str = queries.get(ext, queries["js"])
        query = Query(lang, query_str)
        cursor = QueryCursor(query)
        matches = cursor.matches(tree.root_node)
        
        current_func_name = None
        for _, captures in matches:
            for tag, nodes in captures.items():
                for node in nodes:
                    name = content[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
                    
                    if tag == "class":
                        ladybug_client.execute(
                            "MATCH (d:Directory {path: $dir}) MERGE (c:Class {name: $name, file: $file}) MERGE (d)-[:CONTAINS]->(c)",
                            {"dir": os.path.dirname(file_path), "name": name, "file": file_path}
                        )
                    elif tag == "func":
                        current_func_name = name
                        ladybug_client.execute(
                            "MATCH (d:Directory {path: $dir}) MERGE (f:Function {name: $name, file: $file}) MERGE (d)-[:CONTAINS]->(f)",
                            {"dir": os.path.dirname(file_path), "name": name, "file": file_path}
                        )
                    elif tag == "call" and current_func_name:
                        ladybug_client.execute(
                            "MERGE (caller:Function {name: $caller}) "
                            "MERGE (callee:Function {name: $callee}) "
                            "MERGE (caller)-[:CALLS]->(callee)",
                            {"caller": current_func_name, "callee": name}
                        )

    def _semantic_chunking_to_vector_db(self, file_path: str, tree, content: bytes):
        chunks, metadatas, ids = [], [], []
        
        # Walk the tree to find significant blocks
        def walk_for_chunks(node):
            if node.type in ["class_definition", "function_definition", "class_declaration", "function_declaration", "method_definition"]:
                chunk_text = content[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
                if len(chunk_text.strip()) > 20:
                    chunks.append(chunk_text)
                    metadatas.append({"file_path": file_path, "type": node.type})
                    ids.append(f"{file_path}_{node.start_byte}")
            
            for child in node.children:
                walk_for_chunks(child)

        walk_for_chunks(tree.root_node)
        
        # If no semantic blocks found, fallback to full file
        if not chunks:
            text = content.decode("utf-8", errors="ignore")
            if text.strip():
                chunks.append(text)
                metadatas.append({"file_path": file_path, "type": "full_file"})
                ids.append(f"{file_path}_full")

        if chunks:
            chroma_client.add_documents(chunks, metadatas, ids)

    def _fallback_chunking(self, file_path: str, content: bytes):
        """Simple line-based chunking for files where AST failed."""
        text = content.decode("utf-8", errors="ignore")
        lines = text.split("\n")
        chunk_size = 50
        for i in range(0, len(lines), chunk_size):
            chunk = "\n".join(lines[i:i+chunk_size])
            chroma_client.add_documents([chunk], [{"file_path": file_path, "type": "fallback"}], [f"{file_path}_fb_{i}"])
