import pytest
import concurrent.futures
from unittest.mock import MagicMock, patch
from pathlib import Path


def test_chroma_client_concurrency(tmp_path):
    from app.vector_store.chroma_client import ChromaClient, _client_cache

    # Clear cache for clean test
    _client_cache.clear()

    test_path = tmp_path / "chroma_concurrency"

    with patch("chromadb.PersistentClient") as mock_client:
        # Simulate multiple threads trying to init the same client
        def get_client():
            return ChromaClient(str(test_path))

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_client) for _ in range(10)]
            results = [f.result() for f in futures]

        # Verify only one real initialization happened
        assert mock_client.call_count == 1
        # Verify all threads got the same instance (shared client object)
        first_instance_client = results[0].client
        for res in results:
            assert res.client == first_instance_client


def test_ladybug_client_concurrency(tmp_path):
    from app.db.ladybug_db import LadybugClient, _client_cache

    _client_cache.clear()
    test_path = tmp_path / "ladybug_concurrency"

    with patch("ladybug.Database") as mock_db:

        def get_client():
            client = LadybugClient(str(test_path))
            # Trigger lazy load
            _ = client.db
            return client

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_client) for _ in range(10)]
            results = [f.result() for f in futures]

        # Verify only one real database open happened
        assert mock_db.call_count == 1
        first_db = results[0].db
        for res in results:
            assert res.db == first_db
