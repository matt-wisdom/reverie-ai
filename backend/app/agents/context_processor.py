import os
import re
import uuid
import shutil
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from pypdf import PdfReader
from ..db.ladybug_db import LadybugClient
from ..vector_store.chroma_client import ChromaClient
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class ContextProcessor:
    def __init__(self, tag: str, project_dir: Path):
        self.tag = tag
        self.project_dir = project_dir
        self.docs_dir = project_dir / "context_docs"
        self.docs_dir.mkdir(exist_ok=True)
        self.ladybug_client = LadybugClient(db_path=project_dir / "graph_db")
        self.chroma_client = ChromaClient(path=project_dir / "vector_db")

    async def add_context(self, source: str, doc_type: str = "reference"):
        """Downloads/copies file and processes it into the system."""
        doc_id = str(uuid.uuid4())[:8]
        file_name = source.split("/")[-1].split("?")[0]
        local_path = self.docs_dir / file_name

        if source.startswith(("http://", "https://")):
            logger.info(f"Downloading context from {source}")
            response = requests.get(source)
            with open(local_path, "wb") as f:
                f.write(response.content)
        else:
            source_path = Path(source)
            if not source_path.exists():
                raise FileNotFoundError(f"Source file {source} not found.")
            shutil.copy(source_path, local_path)

        logger.info(f"Processing context document: {file_name}")
        chunks = self._chunk_document(local_path)
        
        # Index in LadybugDB
        added_at = datetime.utcnow().isoformat()
        self.ladybug_client.execute(
            "MERGE (d:ContextDoc {doc_id: $id}) SET d.type = $type, d.title = $title, d.source_path = $path, d.chunk_count = $count, d.added_at = $at",
            {"id": doc_id, "type": doc_type, "title": file_name, "path": str(local_path), "count": len(chunks), "at": added_at}
        )

        # Embed into Chroma
        docs, metadatas, ids = [], [], []
        for i, chunk in enumerate(chunks):
            docs.append(chunk["text"])
            metadatas.append({
                "doc_id": doc_id,
                "breadcrumb": chunk["breadcrumb"],
                "source": file_name
            })
            ids.append(f"doc_{doc_id}_{i}")
        
        self.chroma_client.add_documents(docs, metadatas, ids)
        return doc_id

    def _chunk_document(self, path: Path) -> List[Dict]:
        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._chunk_pdf(path)
        elif ext in [".md", ".txt"]:
            return self._chunk_text(path)
        else:
            logger.warning(f"Unsupported document type: {ext}. Treating as text.")
            return self._chunk_text(path)

    def _chunk_pdf(self, path: Path) -> List[Dict]:
        reader = PdfReader(path)
        content_map = []
        
        # Simple heading detection for breadcrumbs
        # A more advanced version would use reader.outline
        current_breadcrumb = [path.name]
        
        full_text_with_meta = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            # Heuristic: Find lines that look like headings (short, uppercase, or starting with numbers)
            lines = text.split("\n")
            for line in lines:
                clean_line = line.strip()
                if 3 < len(clean_line) < 60 and (clean_line.isupper() or re.match(r"^\d+(\.\d+)*\s+", clean_line)):
                    # Potential heading
                    breadcrumb_str = " > ".join(current_breadcrumb + [clean_line])
                    full_text_with_meta.append({"type": "heading", "text": clean_line, "breadcrumb": breadcrumb_str})
                else:
                    breadcrumb_str = " > ".join(current_breadcrumb)
                    full_text_with_meta.append({"type": "text", "text": clean_line, "breadcrumb": breadcrumb_str})

        return self._hierarchical_split(full_text_with_meta)

    def _chunk_text(self, path: Path) -> List[Dict]:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        
        # For plain text/MD, we split at ~600 tokens (approx 2400 chars)
        sentences = re.split(r'(?<=[.!?]) +', text)
        chunks = []
        current_chunk = []
        current_len = 0
        
        for sent in sentences:
            current_chunk.append(sent)
            current_len += len(sent)
            if current_len > 2000: # ~500-600 tokens
                text_block = " ".join(current_chunk)
                chunks.append({"text": f"[{path.name}] {text_block}", "breadcrumb": path.name})
                # 15% Overlap: Keep last 2 sentences
                current_chunk = current_chunk[-2:] if len(current_chunk) > 2 else []
                current_len = sum(len(s) for s in current_chunk)
        
        if current_chunk:
            chunks.append({"text": f"[{path.name}] {' '.join(current_chunk)}", "breadcrumb": path.name})
            
        return chunks

    def _hierarchical_split(self, text_items: List[Dict]) -> List[Dict]:
        """Further splits large sections into 600-token chunks with overlap."""
        final_chunks = []
        
        current_section = []
        current_breadcrumb = ""
        
        for item in text_items:
            if item["type"] == "heading":
                if current_section:
                    final_chunks.extend(self._sub_split(current_section, current_breadcrumb))
                    current_section = []
                current_breadcrumb = item["breadcrumb"]
            current_section.append(item["text"])
            
        if current_section:
            final_chunks.extend(self._sub_split(current_section, current_breadcrumb))
            
        return final_chunks

    def _sub_split(self, lines: List[str], breadcrumb: str) -> List[Dict]:
        section_text = "\n".join(lines)
        if len(section_text) < 2400:
            return [{"text": f"[{breadcrumb}] {section_text}", "breadcrumb": breadcrumb}]
        
        # Split large section at paragraph or sentence boundaries
        paragraphs = section_text.split("\n\n")
        sub_chunks = []
        curr_para = []
        curr_len = 0
        
        for p in paragraphs:
            curr_para.append(p)
            curr_len += len(p)
            if curr_len > 2000:
                block = "\n\n".join(curr_para)
                sub_chunks.append({"text": f"[{breadcrumb}] {block}", "breadcrumb": breadcrumb})
                # Overlap
                curr_para = curr_para[-1:] # Keep last paragraph
                curr_len = len(curr_para[0])
                
        if curr_para:
            sub_chunks.append({"text": f"[{breadcrumb}] {'\n\n'.join(curr_para)}", "breadcrumb": breadcrumb})
            
        return sub_chunks
