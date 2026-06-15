import chromadb
import os
import google.generativeai as genai
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from ..core.config import (
    get_gemini_api_key, 
    get_gemini_model, 
    GEMINI_EMBEDDING_MODEL, 
    HF_EMBEDDING_MODEL, 
    get_embedding_provider
)
from ..core.logging_config import get_logger
import asyncio
import threading

logger = get_logger(__name__)

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name
        genai.configure(api_key=self.api_key)

    def __call__(self, input: Documents) -> Embeddings:
        result = genai.embed_content(
            model=self.model_name,
            content=input,
            task_type="retrieval_document"
        )
        return result["embedding"]

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
            
        provider = get_embedding_provider()
        logger.info(f"Initializing Chroma at {path} using {provider}")
        
        self.client = chromadb.PersistentClient(path=path)
        
        if provider == "gemini":
            api_key = get_gemini_api_key()
            if not api_key:
                logger.error("GEMINI_API_KEY not set for embeddings. Check your .env files.")
            self.embedding_fn = GeminiEmbeddingFunction(
                api_key=api_key or "missing",
                model_name=GEMINI_EMBEDDING_MODEL
            )
        else:
            from chromadb.utils import embedding_functions
            self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=HF_EMBEDDING_MODEL
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
