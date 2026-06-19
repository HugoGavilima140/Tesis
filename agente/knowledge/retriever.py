"""
agente/knowledge/retriever.py — Business Knowledge Retriever.

Responsabilidades:
  - Indexar los chunks de la KB con embeddings sentence-transformers + FAISS.
  - Recuperar chunks relevantes dado una pregunta (búsqueda semántica).
  - Formatear el contexto empresarial para los prompts LLM.
  - Persistir el índice en disco para evitar re-indexar en cada ejecución.

Usa la misma infraestructura de embeddings que el proyecto WikiSQL base.
"""

import json
import pickle
from pathlib import Path
from typing import List, Optional

import numpy as np

from agente.config import (
    EMBED_MODEL, EMBED_DIM, KB_INDEX_DIR, TOP_K_KB,
    KB_CHUNK_SIZE, KB_CHUNK_OVERLAP, KB_DIR,
)
from agente.knowledge.loader import KBChunk, KnowledgeBaseLoader


class BusinessKnowledgeRetriever:
    """
    Recuperador semántico sobre la base de conocimiento de PayNova.

    Flujo:
    1. Carga chunks de los archivos Markdown.
    2. Genera embeddings con sentence-transformers.
    3. Construye índice FAISS.
    4. En cada consulta: embed pregunta → buscar top-K chunks → devolver contexto.
    """

    INDEX_FILE  = KB_INDEX_DIR / "kb.faiss"
    CHUNKS_FILE = KB_INDEX_DIR / "kb_chunks.pkl"

    def __init__(self, kb_dir: Optional[Path] = None):
        self.kb_dir = Path(kb_dir) if kb_dir else KB_DIR
        self._model  = None   # lazy load
        self._index  = None   # FAISS index
        self._chunks: List[KBChunk] = []

    # ──────────────────────────────────────────────────────────────────────────
    # Inicialización pública
    # ──────────────────────────────────────────────────────────────────────────

    def initialize(self, force_rebuild: bool = False) -> int:
        """
        Carga o construye el índice FAISS.

        Returns:
            Número de chunks indexados.
        """
        if not force_rebuild and self._load_index():
            return len(self._chunks)

        print("[KB Retriever] Construyendo índice de base de conocimiento...")
        loader = KnowledgeBaseLoader(self.kb_dir, KB_CHUNK_SIZE, KB_CHUNK_OVERLAP)
        self._chunks = loader.load_all()

        embeddings = self._embed_texts([c.full_text for c in self._chunks])
        self._build_faiss(embeddings)
        self._save_index()

        print(f"[KB Retriever] Indexados {len(self._chunks)} chunks de la KB.")
        return len(self._chunks)

    # ──────────────────────────────────────────────────────────────────────────
    # Recuperación
    # ──────────────────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = TOP_K_KB) -> List[KBChunk]:
        """
        Recupera los chunks más relevantes para la consulta.

        Args:
            query:  Pregunta o texto de consulta.
            top_k:  Número de chunks a devolver.

        Returns:
            Lista de KBChunk ordenados por relevancia.
        """
        if not self._chunks:
            self.initialize()

        query_emb = self._embed_texts([query])
        D, I = self._index.search(query_emb.astype("float32"), min(top_k, len(self._chunks)))

        results = []
        for idx in I[0]:
            if 0 <= idx < len(self._chunks):
                results.append(self._chunks[idx])
        return results

    def format_context(self, chunks: List[KBChunk], max_chars: int = 3000) -> str:
        """
        Formatea los chunks recuperados en un contexto legible para el LLM.
        """
        parts = []
        total = 0
        for chunk in chunks:
            text = f"### [{chunk.doc_id}] {chunk.section}\n{chunk.content}"
            if total + len(text) > max_chars:
                break
            parts.append(text)
            total += len(text)
        return "\n\n---\n\n".join(parts)

    def retrieve_formatted(self, query: str, top_k: int = TOP_K_KB) -> str:
        """Convenience: retrieve + format en un solo paso."""
        chunks = self.retrieve(query, top_k)
        return self.format_context(chunks)

    # ──────────────────────────────────────────────────────────────────────────
    # Internos: embeddings
    # ──────────────────────────────────────────────────────────────────────────

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMBED_MODEL)
        return self._model

    def _embed_texts(self, texts: List[str]) -> np.ndarray:
        model = self._get_model()
        return model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Internos: FAISS
    # ──────────────────────────────────────────────────────────────────────────

    def _build_faiss(self, embeddings: np.ndarray) -> None:
        import faiss
        dim = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)  # Inner Product = cosine similarity con normalize
        self._index.add(embeddings.astype("float32"))

    def _save_index(self) -> None:
        import faiss
        faiss.write_index(self._index, str(self.INDEX_FILE))
        with open(self.CHUNKS_FILE, "wb") as f:
            pickle.dump(self._chunks, f)

    def _load_index(self) -> bool:
        if not self.INDEX_FILE.exists() or not self.CHUNKS_FILE.exists():
            return False
        try:
            import faiss
            self._index = faiss.read_index(str(self.INDEX_FILE))
            with open(self.CHUNKS_FILE, "rb") as f:
                self._chunks = pickle.load(f)
            print(f"[KB Retriever] Índice cargado ({len(self._chunks)} chunks).")
            return True
        except Exception as e:
            print(f"[KB Retriever] No se pudo cargar índice: {e}")
            return False
