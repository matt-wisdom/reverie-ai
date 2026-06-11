import ladybug
import os
import shutil
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
        """Forcefully initialize the schema table by table."""
        tables = {
            "NODE": [
                "Project(id STRING, name STRING, created_at STRING, last_reviewed_at STRING, tech_stack STRING[], PRIMARY KEY (id))",
                "File(path STRING, language STRING, last_seen STRING, review_count INT64, PRIMARY KEY (path))",
                "Finding(finding_id STRING, title STRING, category STRING, severity STRING, owasp_category STRING, cwe_id STRING, description STRING, first_seen STRING, last_seen STRING, occurrences INT64, status STRING, PRIMARY KEY (finding_id))",
                "Pattern(pattern_id STRING, description STRING, promoted_at STRING, occurrence_threshold_met BOOLEAN, PRIMARY KEY (pattern_id))",
                "ContextDoc(doc_id STRING, type STRING, title STRING, source_path STRING, chunk_count INT64, added_at STRING, PRIMARY KEY (doc_id))",
                "Decision(decision_id STRING, title STRING, rationale STRING, applies_to STRING, created_at STRING, PRIMARY KEY (decision_id))",
                "Suppression(suppression_id STRING, rule_id STRING, reason STRING, file_path STRING, line INT64, created_at STRING, PRIMARY KEY (suppression_id))",
                "Session(session_id STRING, started_at STRING, completed_at STRING, mode STRING, commit_ref STRING, PRIMARY KEY (session_id))",
                "Directory(path STRING, summary STRING, context STRING, PRIMARY KEY (path))",
                "Module(path STRING, content STRING, PRIMARY KEY (path))",
                "Class(id STRING, name STRING, docstring STRING, file STRING, PRIMARY KEY (id))",
                "Function(id STRING, name STRING, signature STRING, is_method BOOLEAN, file STRING, PRIMARY KEY (id))"
            ],
            "REL": [
                "FINDING_IN_PROJ(FROM Finding TO Project)",
                "FILE_IN_PROJ(FROM File TO Project)",
                "DETECTED_IN(FROM Finding TO File, line_hint INT64, first_seen STRING, last_seen STRING, occurrences INT64)",
                "RECURS_IN(FROM Pattern TO File)",
                "PROMOTED_FROM(FROM Pattern TO Finding)",
                "RELATED_TO(FROM Finding TO Finding)",
                "COVERS(FROM Decision TO File)",
                "SUPPRESSES(FROM Suppression TO Finding)",
                "REVIEWED_IN(FROM File TO Session)",
                "REFERENCES(FROM Finding TO ContextDoc)",
                "DIR_TO_MODULE(FROM Directory TO Module)",
                "MOD_TO_CLASS(FROM Module TO Class)",
                "MOD_TO_FUNC(FROM Module TO Function)",
                "CLASS_TO_FUNC(FROM Class TO Function)",
                "CALLS(FROM Function TO Function)"
            ]
        }

        for node_table in tables["NODE"]:
            try:
                self.execute(f"CREATE NODE TABLE {node_table}")
                logger.debug(f"Created node table: {node_table.split('(')[0]}")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.error(f"Error creating node table {node_table}: {e}")

        for rel_table in tables["REL"]:
            try:
                self.execute(f"CREATE REL TABLE {rel_table}")
                logger.debug(f"Created rel table: {rel_table.split('(')[0]}")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.error(f"Error creating rel table {rel_table}: {e}")

        logger.info("Knowledge Graph schema check/init complete.")
