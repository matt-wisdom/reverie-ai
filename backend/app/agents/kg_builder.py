import ast
from ..db.ladybug_db import ladybug_client
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class KGBuilder:
    @staticmethod
    def build_from_code(path: str, code: str):
        """Simple AST-based parser to populate the knowledge graph."""
        logger.debug(f"Building KG from {path}")
        tree = ast.parse(code)
        
        # Insert Module
        ladybug_client.execute(
            "MERGE (m:Module {path: $path}) SET m.content = $content",
            {"path": path, "content": code}
        )
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                ladybug_client.execute(
                    "MERGE (c:Class {name: $name}) SET c.docstring = $doc",
                    {"name": node.name, "doc": ast.get_docstring(node) or ""}
                )
                ladybug_client.execute(
                    "MATCH (m:Module {path: $path}), (c:Class {name: $name}) MERGE (m)-[:CONTAINS]->(c)",
                    {"path": path, "name": node.name}
                )
                
            elif isinstance(node, ast.FunctionDef):
                ladybug_client.execute(
                    "MERGE (f:Function {name: $name}) SET f.signature = $sig, f.is_method = $is_method",
                    {"name": node.name, "sig": node.name, "is_method": False} # Simplified
                )
                ladybug_client.execute(
                    "MATCH (m:Module {path: $path}), (f:Function {name: $name}) MERGE (m)-[:CONTAINS]->(f)",
                    {"path": path, "name": node.name}
                )
        
        return "Knowledge Graph updated."
