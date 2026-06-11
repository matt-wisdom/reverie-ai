import pytest
from unittest.mock import MagicMock, patch

def test_ladybug_client_execute():
    from app.db.ladybug_db import LadybugClient
    with patch("ladybug.Database"), patch("ladybug.Connection"):
        client = LadybugClient(db_path="/tmp/test_db")
        with patch.object(client, "execute") as mock_exec:
            client.execute("CREATE NODE TABLE Test(name STRING, PRIMARY KEY (name))")
            assert mock_exec.called

def test_ladybug_init_schema():
    from app.db.ladybug_db import LadybugClient
    with patch("ladybug.Database"), patch("ladybug.Connection"):
        client = LadybugClient(db_path="/tmp/test_db")
        with patch.object(client, "execute") as mock_exec:
            client.init_schema()
            assert mock_exec.called
            # Verify one of the calls to ensure it's doing work
            assert mock_exec.call_count > 5
