import chromadb
import os
import google.generativeai as genai
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from ..core.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL_TYPE,
    GEMINI_EMBEDDING_MODEL,
    gemini_limiter,
)
from ..core.logging_config import get_logger
import asyncio
import threading

logger = get_logger(__name__)


class GoogleGeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, model_name: str = GEMINI_EMBEDDING_MODEL):
        self.api_key = api_key
        self.model_name = model_name
        genai.configure(api_key=self.api_key)

    def __call__(self, input: Documents) -> Embeddings:
        # chroma's __call__ is sync and we are running inside an async ingestion pipeline.
        result = genai.embed_content(
            model=self.model_name, content=input, task_type="retrieval_document"
        )
        return result["embedding"]


# Global cache for project-specific clients to avoid concurrent initialization issues
_client_cache = {}
_cache_lock = threading.Lock()


class ChromaClient:
    def __init__(self, path: str):
        path_str = str(path)
        with _cache_lock:
            if path_str in _client_cache:
                self.client = _client_cache[path_str].client
                self.embedding_function = _client_cache[path_str].embedding_function
                self.collection = _client_cache[path_str].collection
                return

            logger.info(f"Initializing new Chroma PersistentClient at {path_str}")
            self.client = chromadb.PersistentClient(path=path_str)
            self.embedding_function = GoogleGeminiEmbeddingFunction(
                api_key=GEMINI_API_KEY, model_name=GEMINI_EMBEDDING_MODEL
            )
            self.collection = self.client.get_or_create_collection(
                name="code_snippets", embedding_function=self.embedding_function
            )
            _client_cache[path_str] = self

    def add_documents(
        self, documents: list[str], metadatas: list[dict], ids: list[str]
    ):
        self.collection.add(documents=documents, metadatas=metadatas, ids=ids)

    def query(self, query_texts: list[str], n_results: int = 5):
        # 1. Vector Search (Cosine Similarity via Gemini)
        vector_results = self.collection.query(
            query_texts=query_texts,
            n_results=n_results * 2,  # Get more candidates for reranking
        )

        # 2. Simple BM25-like reranking (Keyword Boosting)
        # In a real production setup, we'd use a dedicated cross-encoder or BM25 index.
        # Here we simulate by boosting results containing exact query tokens.
        boosted_results = []
        keywords = set(query_texts[0].lower().split())

        for i in range(len(vector_results["ids"][0])):
            doc = vector_results["documents"][0][i]
            meta = vector_results["metadatas"][0][i]
            dist = vector_results["distances"][0][i]

            score = 1.0 - dist  # Higher is better
            match_count = sum(1 for kw in keywords if kw in doc.lower())
            score += match_count * 0.1  # Boost for keyword matches

            boosted_results.append(
                {
                    "id": vector_results["ids"][0][i],
                    "document": doc,
                    "metadata": meta,
                    "score": score,
                }
            )

        # Sort by boosted score
        boosted_results.sort(key=lambda x: x["score"], reverse=True)
        return boosted_results[:n_results]
