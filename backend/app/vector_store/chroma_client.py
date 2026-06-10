import chromadb
import os
import google.generativeai as genai
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from ..core.config import GEMINI_API_KEY, GEMINI_MODEL_TYPE, GEMINI_EMBEDDING_MODEL, gemini_limiter
import asyncio

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")

class GoogleGeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, model_name: str = GEMINI_EMBEDDING_MODEL):
        self.api_key = api_key
        self.model_name = model_name
        genai.configure(api_key=self.api_key)

    def __call__(self, input: Documents) -> Embeddings:
        # chroma's __call__ is sync and we are running inside an async ingestion pipeline.
        # Calling asyncio.run or loop.run_until_complete from within a running loop fails.
        # We will use the synchronous genai.embed_content call instead.
        
        result = genai.embed_content(
            model=self.model_name,
            content=input,
            task_type="retrieval_document"
        )
        return result["embedding"]

class ChromaClient:
    def __init__(self, path: str = CHROMA_PATH):
        self.client = chromadb.PersistentClient(path=path)
        self.embedding_function = GoogleGeminiEmbeddingFunction(
            api_key=GEMINI_API_KEY,
            model_name=GEMINI_EMBEDDING_MODEL
        )
        self.collection = self.client.get_or_create_collection(
            name="code_snippets",
            embedding_function=self.embedding_function
        )

    def add_documents(self, documents: list[str], metadatas: list[dict], ids: list[str]):
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

    def query(self, query_texts: list[str], n_results: int = 5):
        return self.collection.query(
            query_texts=query_texts,
            n_results=n_results
        )

chroma_client = ChromaClient()
