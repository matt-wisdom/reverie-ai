import chromadb
from chromadb.utils.embedding_functions import GoogleGenerativeAiEmbeddingFunction
import os

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

class ChromaClient:
    def __init__(self, path: str = CHROMA_PATH):
        self.client = chromadb.PersistentClient(path=path)
        self.embedding_function = GoogleGenerativeAiEmbeddingFunction(
            api_key=GOOGLE_API_KEY,
            model_name="models/embedding-001"
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
