import ast
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class KGBuilder:
    def __init__(self, ladybug_client):
        self.ladybug_client = ladybug_client

    def build_from_code(self, path: str, code: str):
        """Simple AST-based parser to populate the knowledge graph."""
        logger.debug(f"Building KG from {path}")
        tree = ast.parse(code)
        
        # Insert Module
        self.ladybug_client.execute(
            "MERGE (m:Module {path: $path}) SET m.content = $content",
            {"path": path, "content": code}
        )
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self.ladybug_client.execute(
                    "MERGE (c:Class {id: $id}) SET c.name = $name, c.docstring = $doc, c.file = $path",
                    {"id": f"{path}:{node.name}", "name": node.name, "doc": ast.get_docstring(node) or "", "path": path}
                )
                self.ladybug_client.execute(
                    "MATCH (m:Module {path: $path}), (c:Class {id: $id}) MERGE (m)-[:MOD_TO_CLASS]->(c)",
                    {"path": path, "id": f"{path}:{node.name}"}
                )
                
            elif isinstance(node, ast.FunctionDef):
                self.ladybug_client.execute(
                    "MERGE (f:Function {id: $id}) SET f.name = $name, f.signature = $sig, f.is_method = $is_method, f.file = $path",
                    {"id": f"{path}:{node.name}", "name": node.name, "sig": node.name, "is_method": False, "path": path}
                )
                self.ladybug_client.execute(
                    "MATCH (m:Module {path: $path}), (f:Function {id: $id}) MERGE (m)-[:MOD_TO_FUNC]->(f)",
                    {"path": path, "id": f"{path}:{node.name}"}
                )
        
        return "Knowledge Graph updated."
