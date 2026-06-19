"""
agente/knowledge/loader.py — Cargador y chunkeador de la base de conocimiento.

Carga todos los archivos Markdown de la KB de PayNova y los divide en
chunks semánticos para indexación y recuperación.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class KBChunk:
    """Un fragmento de la base de conocimiento."""
    doc_id: str           # nombre del archivo (sin extensión)
    section: str          # título de la sección (# Heading)
    content: str          # texto del chunk
    metadata: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return f"[{self.doc_id}] {self.section}\n{self.content}"


class KnowledgeBaseLoader:
    """
    Carga y chunkea la base de conocimiento en Markdown.

    Estrategia de chunking:
    - Divide por secciones (líneas que empiezan con #)
    - Cada sección es un chunk independiente
    - Si una sección es muy larga, se subdivide por párrafos
    """

    def __init__(self, kb_dir: Path, chunk_size: int = 800, overlap: int = 100):
        self.kb_dir   = Path(kb_dir)
        self.chunk_size  = chunk_size
        self.overlap     = overlap

    def load_all(self) -> List[KBChunk]:
        """Carga todos los .md del directorio KB."""
        chunks: List[KBChunk] = []
        md_files = sorted(self.kb_dir.glob("*.md"))

        if not md_files:
            raise FileNotFoundError(f"No se encontraron archivos .md en: {self.kb_dir}")

        for md_file in md_files:
            doc_chunks = self._load_file(md_file)
            chunks.extend(doc_chunks)

        return chunks

    def _load_file(self, path: Path) -> List[KBChunk]:
        """Carga un archivo .md y lo divide en chunks por sección."""
        doc_id = path.stem
        text   = path.read_text(encoding="utf-8")

        sections = self._split_by_headings(text)
        chunks: List[KBChunk] = []

        for section_title, section_body in sections:
            if not section_body.strip():
                continue

            # Si la sección cabe en un chunk, guardarla directamente
            if len(section_body) <= self.chunk_size:
                chunks.append(KBChunk(
                    doc_id=doc_id,
                    section=section_title,
                    content=section_body.strip(),
                    metadata={"source": str(path)},
                ))
            else:
                # Subdivir por párrafos manteniendo overlap
                sub_chunks = self._split_large_section(doc_id, section_title, section_body, path)
                chunks.extend(sub_chunks)

        return chunks

    def _split_by_headings(self, text: str) -> List[tuple]:
        """Divide el texto en (título, cuerpo) por encabezados Markdown."""
        pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))

        if not matches:
            return [("Contenido", text)]

        sections = []
        for i, match in enumerate(matches):
            title    = match.group(2).strip()
            start    = match.end()
            end      = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body     = text[start:end]
            sections.append((title, body))

        return sections

    def _split_large_section(
        self, doc_id: str, section: str, body: str, path: Path
    ) -> List[KBChunk]:
        """Divide una sección grande en chunks con overlap."""
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        chunks = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) <= self.chunk_size:
                current += "\n\n" + para
            else:
                if current:
                    chunks.append(KBChunk(
                        doc_id=doc_id,
                        section=section,
                        content=current.strip(),
                        metadata={"source": str(path)},
                    ))
                # Overlap: mantener el último párrafo del chunk anterior
                current = (current[-self.overlap:] if len(current) > self.overlap else current)
                current += "\n\n" + para

        if current.strip():
            chunks.append(KBChunk(
                doc_id=doc_id,
                section=section,
                content=current.strip(),
                metadata={"source": str(path)},
            ))

        return chunks
