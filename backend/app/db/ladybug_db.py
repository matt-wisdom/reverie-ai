import ladybug
import os

from ..core.logging_config import get_logger

logger = get_logger(__name__)
LADYBUG_DB_PATH = os.getenv("LADYBUG_DB_PATH", "ladybug_graph.db")

class LadybugClient:
    def __init__(self, db_path: str = LADYBUG_DB_PATH):
        self.db = ladybug.Database(db_path)
        self.conn = ladybug.Connection(self.db)

    def execute(self, query: str, params: dict = None):
        # Ladybug/Kuzu usually uses Cypher
        return self.conn.execute(query, params or {})

    def init_schema(self):
        try:
            # Nodes
            self.conn.execute("CREATE NODE TABLE Directory(path STRING, summary TEXT, context TEXT, PRIMARY KEY (path))")
            self.conn.execute("CREATE NODE TABLE Module(path STRING, content TEXT, PRIMARY KEY (path))")
            self.conn.execute("CREATE NODE TABLE Class(name STRING, docstring TEXT, PRIMARY KEY (name))")
            self.conn.execute("CREATE NODE TABLE Function(name STRING, signature STRING, is_method BOOLEAN, PRIMARY KEY (name))")
            self.conn.execute("CREATE NODE TABLE Variable(name STRING, type STRING, PRIMARY KEY (name))")
            
            # Relationships
            self.conn.execute("CREATE REL TABLE CONTAINS(FROM Module TO Class)")
            self.conn.execute("CREATE REL TABLE CONTAINS(FROM Module TO Function)")
            self.conn.execute("CREATE REL TABLE CONTAINS(FROM Class TO Function)")
            self.conn.execute("CREATE REL TABLE CALLS(FROM Function TO Function)")
            self.conn.execute("CREATE REL TABLE DEPENDS_ON(FROM Module TO Module)")
            self.conn.execute("CREATE REL TABLE USES(FROM Function TO Variable)")
            
            logger.info("Knowledge Graph schema initialized successfully.")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug("Knowledge Graph schema already exists.")
            else:
                logger.error(f"Error initializing schema: {e}")

ladybug_client = LadybugClient()
