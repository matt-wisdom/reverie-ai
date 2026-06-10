import ladybug
import os

from ..core.logging_config import get_logger

logger = get_logger(__name__)

class LadybugClient:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self._db = None
        self._conn = None

    @property
    def db(self):
        if self._db is None:
            try:
                self._db = ladybug.Database(self.db_path)
            except Exception as e:
                logger.error(f"Failed to open LadybugDB at {self.db_path}: {e}")
                if "Corrupted" in str(e):
                    logger.warning("Attempting to recover by deleting corrupted DB files...")
                    import shutil
                    if os.path.exists(self.db_path):
                        shutil.rmtree(self.db_path)
                    self._db = ladybug.Database(self.db_path)
                else:
                    raise e
        return self._db

    @property
    def conn(self):
        if self._conn is None:
            self._conn = ladybug.Connection(self.db)
        return self._conn

    def execute(self, query: str, params: dict = None):
        return self.conn.execute(query, params or {})

    def init_schema(self):
        try:
            # Nodes
            self.conn.execute("CREATE NODE TABLE Directory(path STRING, summary STRING, context STRING, PRIMARY KEY (path))")
            self.conn.execute("CREATE NODE TABLE Module(path STRING, content STRING, PRIMARY KEY (path))")
            self.conn.execute("CREATE NODE TABLE Class(id STRING, name STRING, docstring STRING, file STRING, PRIMARY KEY (id))")
            self.conn.execute("CREATE NODE TABLE Function(id STRING, name STRING, signature STRING, is_method BOOLEAN, file STRING, PRIMARY KEY (id))")
            self.conn.execute("CREATE NODE TABLE Variable(id STRING, name STRING, type STRING, PRIMARY KEY (id))")
            
            # Relationships
            self.conn.execute("CREATE REL TABLE DIR_TO_MODULE(FROM Directory TO Module)")
            self.conn.execute("CREATE REL TABLE DIR_TO_CLASS(FROM Directory TO Class)")
            self.conn.execute("CREATE REL TABLE DIR_TO_FUNC(FROM Directory TO Function)")
            self.conn.execute("CREATE REL TABLE MOD_TO_CLASS(FROM Module TO Class)")
            self.conn.execute("CREATE REL TABLE MOD_TO_FUNC(FROM Module TO Function)")
            self.conn.execute("CREATE REL TABLE CLASS_TO_FUNC(FROM Class TO Function)")
            self.conn.execute("CREATE REL TABLE CALLS(FROM Function TO Function)")
            self.conn.execute("CREATE REL TABLE DEPENDS_ON(FROM Module TO Module)")
            self.conn.execute("CREATE REL TABLE USES(FROM Function TO Variable)")
            
            logger.info("Knowledge Graph schema initialized successfully.")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug("Knowledge Graph schema already exists.")
            else:
                logger.error(f"Error initializing schema: {e}")
