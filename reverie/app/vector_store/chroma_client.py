import chromadb
import os
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from langchain_litellm import LiteLLMEmbeddings
from ..core.config import (
    get_embedding_model,
    get_embedding_api_key
)
from ..core.logging_config import get_logger
import asyncio
import threading

logger = get_logger(__name__)

class LiteLLMEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model: str, api_key: str = None):
        self.ef = LiteLLMEmbeddings(model=model, api_key=api_key)

    def __call__(self, input: Documents) -> Embeddings:
        return self.ef.embed_documents(input)

class ChromaClient:
    _instances = {}
    _lock = threading.Lock()

    def __new__(cls, path: str = "./chroma_db"):
        with cls._lock:
            if path not in cls._instances:
                instance = super(ChromaClient, cls).__new__(cls)
                instance._initialized = False
                cls._instances[path] = instance
            return cls._instances[path]

    def __init__(self, path: str = "./chroma_db"):
        if self._initialized:
            return
            
        model_name = get_embedding_model()
        logger.info(f"Initializing Chroma at {path} using LiteLLM model: {model_name}")
        
        self.client = chromadb.PersistentClient(path=path)
        
        # LiteLLM handles both cloud (OpenAI/Gemini) and local/hf providers.
        api_key = get_embedding_api_key()
        self.embedding_fn = LiteLLMEmbeddingFunction(
            model=model_name,
            api_key=api_key
        )
            
        self.collection = self.client.get_or_create_collection(
            name="reverie_context",
            embedding_function=self.embedding_fn
        )
        self._initialized = True

    def add_documents(self, documents: list[str], metadatas: list[dict], ids: list[str]):
        self.collection.add(documents=documents, metadatas=metadatas, ids=ids)

    def query(self, query_texts: list[str], n_results: int = 5):
        return self.collection.query(query_texts=query_texts, n_results=n_results)

    def boosted_query(self, query_texts: list[str], n_results: int = 5):
        vector_results = self.collection.query(query_texts=query_texts, n_results=n_results * 2)
        
        boosted_results = []
        for i, doc in enumerate(vector_results["documents"][0]):
            meta = vector_results["metadatas"][0][i]
            score = 1.0
            
            # Boost matches in filenames/paths
            if any(q.lower() in meta.get("file_path", "").lower() for q in query_texts):
                score += 0.5
            
            boosted_results.append({"id": vector_results["ids"][0][i], "document": doc, "metadata": meta, "score": score})
            
        boosted_results.sort(key=lambda x: x["score"], reverse=True)
        return boosted_results[:n_results]
