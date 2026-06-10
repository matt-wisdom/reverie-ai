import os
import sys
from unittest.mock import MagicMock, patch

os.environ["GOOGLE_API_KEY"] = "fake_key"
os.environ["GEMINI_API_KEY"] = "fake_key"

import pytest

def test_ladybug_client_execute():
    # Use a more direct mock for the client's internal connection
    from app.db.ladybug_db import LadybugClient
    with patch("app.db.ladybug_db.ladybug.Connection") as mock_conn_class:
        mock_conn = MagicMock()
        mock_conn_class.return_value = mock_conn
        
        client = LadybugClient(db_path=":memory:")
        client.execute("CREATE NODE TABLE Test(name STRING, PRIMARY KEY (name))")
        
        assert mock_conn.execute.called

def test_ladybug_init_schema():
    from app.db.ladybug_db import LadybugClient
    with patch("app.db.ladybug_db.ladybug.Connection") as mock_conn_class:
        mock_conn = MagicMock()
        mock_conn_class.return_value = mock_conn
        
        client = LadybugClient()
        client.init_schema()
        
        assert mock_conn.execute.called
