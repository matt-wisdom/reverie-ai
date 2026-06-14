import os
import shutil
import real_ladybug as ladybug
from ..core.logging_config import get_logger

logger = get_logger(__name__)

import threading

_client_cache = {}
_cache_lock = threading.Lock()


class LadybugClient:
    def __init__(self, db_path: str):
        path_str = str(db_path)
        with _cache_lock:
            if path_str in _client_cache:
                self.db_path = _client_cache[path_str].db_path
                self._db = _client_cache[path_str]._db
                self._conn = _client_cache[path_str]._conn
                return

            self.db_path = path_str
            self._db = None
            self._conn = None
            _client_cache[path_str] = self

    @property
    def db(self):
        if self._db is None:
            try:
                self._db = ladybug.Database(self.db_path)
            except Exception as e:
                logger.error(f"Failed to open LadybugDB at {self.db_path}: {e}")
                if "Corrupted" in str(e):
                    logger.warning(
                        "Attempting to recover by deleting corrupted DB files..."
                    )
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
        """Forcefully initialize the schema table by table and handle evolution."""
        # 1. Standard Node Tables
        nodes = {
            "Project": "Project(id STRING, name STRING, created_at STRING, last_reviewed_at STRING, tech_stack STRING[], summary STRING, PRIMARY KEY (id))",
            "File": "File(path STRING, language STRING, last_seen STRING, review_count INT64, hash STRING, PRIMARY KEY (path))",
            "Finding": "Finding(finding_id STRING, title STRING, category STRING, severity STRING, owasp_category STRING, cwe_id STRING, description STRING, first_seen STRING, last_seen STRING, occurrences INT64, status STRING, PRIMARY KEY (finding_id))",
            "Pattern": "Pattern(pattern_id STRING, description STRING, promoted_at STRING, occurrence_threshold_met BOOLEAN, PRIMARY KEY (pattern_id))",
            "ContextDoc": "ContextDoc(doc_id STRING, type STRING, title STRING, source_path STRING, chunk_count INT64, added_at STRING, PRIMARY KEY (doc_id))",
            "Decision": "Decision(decision_id STRING, title STRING, rationale STRING, applies_to STRING, created_at STRING, PRIMARY KEY (decision_id))",
            "Suppression": "Suppression(suppression_id STRING, rule_id STRING, reason STRING, file_path STRING, line INT64, created_at STRING, PRIMARY KEY (suppression_id))",
            "Directory": "Directory(path STRING, summary STRING, context STRING, PRIMARY KEY (path))",
            "Module": "Module(path STRING, PRIMARY KEY (path))",
            "Class": "Class(id STRING, name STRING, file STRING, PRIMARY KEY (id))",
            "Function": "Function(id STRING, name STRING, file STRING, decorator STRING, is_entry_point BOOLEAN, PRIMARY KEY (id))",
        }

        for table_name, schema in nodes.items():
            try:
                self.execute(f"CREATE NODE TABLE {schema}")
                logger.info(f"Created node table: {table_name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    # --- Schema Evolution: Add missing columns if they don't exist ---
                    if table_name == "Project":
                        try:
                            self.execute("ALTER TABLE Project ADD summary STRING")
                        except:
                            pass
                    if table_name == "File":
                        try:
                            self.execute("ALTER TABLE File ADD hash STRING")
                        except:
                            pass
                    if table_name == "Function":
                        try:
                            self.execute("ALTER TABLE Function ADD decorator STRING")
                        except:
                            pass
                        try:
                            self.execute(
                                "ALTER TABLE Function ADD is_entry_point BOOLEAN"
                            )
                        except:
                            pass
                    continue
                logger.error(f"Error creating node table {table_name}: {e}")

        # 2. Relationship Tables
        rels = [
            "FILE_IN_PROJ(FROM File TO Project)",
            "FINDING_IN_FILE(FROM Finding TO File)",
            "DOC_IN_PROJ(FROM ContextDoc TO Project)",
            "PATTERN_FOR_FINDING(FROM Pattern TO Finding)",
            "DIR_TO_MODULE(FROM Directory TO Module)",
            "MOD_TO_CLASS(FROM Module TO Class)",
            "MOD_TO_FUNC(FROM Module TO Function)",
            "CALLS(FROM Function TO Function)",
            "DEPENDS_ON(FROM Module TO Module)",
            "INHERITS_FROM(FROM Class TO Class)",
            "USES(FROM Function TO Finding)",
        ]
        for rel in rels:
            try:
                self.execute(f"CREATE REL TABLE {rel}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    continue
                logger.error(f"Error creating rel table: {e}")

        logger.info("Knowledge Graph schema check/init complete.")
