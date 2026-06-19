"""
agente/agents/memory.py — Memory Agent con persistencia en JSON.

Mantiene memoria de:
  - Errores frecuentes (tablas confundidas, métricas mal calculadas, joins incorrectos)
  - Estrategias exitosas (planes, queries, correcciones)
  - Feedback del usuario (correcciones, aclaraciones, rechazos)
  - Patrones de preguntas frecuentes

La memoria se persiste en disco (JSON) y se carga al inicio de cada sesión.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agente.config import MEMORY_PATH


class MemoryEntry:
    """Una entrada de memoria con timestamp."""
    def __init__(self, entry_type: str, content: Dict[str, Any]):
        self.type      = entry_type
        self.content   = content
        self.timestamp = datetime.now().isoformat()
        self.uses      = 0  # cuántas veces fue recuperada

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
            "uses": self.uses,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "MemoryEntry":
        entry = cls(d["type"], d["content"])
        entry.timestamp = d.get("timestamp", "")
        entry.uses      = d.get("uses", 0)
        return entry


class MemoryAgent:
    """
    Agente de memoria persistente para el Business Reasoning Agent.

    Almacena y recupera:
    - error_patterns: errores SQL frecuentes y cómo se corrigieron
    - success_patterns: queries y planes exitosos por dominio/tipo
    - user_feedback: correcciones y aclaraciones del usuario
    - question_cache: respuestas a preguntas ya respondidas
    """

    MAX_ENTRIES_PER_TYPE = 100  # límite de entradas por tipo

    def __init__(self, memory_path: Optional[Path] = None):
        self.path    = Path(memory_path) if memory_path else MEMORY_PATH
        self._store: Dict[str, List[MemoryEntry]] = {
            "error_patterns":   [],
            "success_patterns": [],
            "user_feedback":    [],
            "question_cache":   [],
        }
        self._load()

    # ──────────────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────────────

    def record_error(
        self,
        question: str,
        sql: str,
        error: str,
        domain: str,
        correction: str = "",
    ) -> None:
        """Registra un error SQL y su corrección."""
        self._add("error_patterns", {
            "question_snippet": question[:100],
            "failed_sql_snippet": sql[:200],
            "error": error[:200],
            "domain": domain,
            "correction": correction[:200],
        })

    def record_success(
        self,
        question: str,
        domain: str,
        complexity: str,
        plan_summary: str,
        sql_snippets: List[str],
        confidence: int,
    ) -> None:
        """Registra un análisis exitoso."""
        self._add("success_patterns", {
            "question_snippet": question[:100],
            "domain": domain,
            "complexity": complexity,
            "plan_summary": plan_summary[:300],
            "sql_snippets": [s[:150] for s in sql_snippets[:3]],
            "confidence": confidence,
        })

    def record_feedback(self, feedback_type: str, content: str) -> None:
        """Registra feedback del usuario."""
        self._add("user_feedback", {
            "feedback_type": feedback_type,
            "content": content[:300],
        })

    def cache_response(self, question: str, response_summary: str) -> None:
        """Cachea la respuesta a una pregunta para recuperación rápida."""
        self._add("question_cache", {
            "question": question,
            "response_summary": response_summary[:500],
        })

    def retrieve_relevant_errors(self, domain: str, top_k: int = 3) -> List[Dict]:
        """Recupera errores frecuentes del mismo dominio."""
        relevant = [
            e.content for e in self._store["error_patterns"]
            if e.content.get("domain") == domain
        ]
        return relevant[-top_k:] if relevant else []

    def retrieve_similar_successes(self, domain: str, complexity: str, top_k: int = 3) -> List[Dict]:
        """Recupera patrones exitosos similares."""
        relevant = [
            e.content for e in self._store["success_patterns"]
            if e.content.get("domain") == domain
            or e.content.get("complexity") == complexity
        ]
        # Priorizar los de mayor confianza
        relevant.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return relevant[:top_k]

    def check_cache(self, question: str, similarity_threshold: int = 80) -> Optional[str]:
        """
        Busca en caché si una pregunta similar ya fue respondida.
        Usa comparación simple de caracteres (no semántica).
        """
        question_lower = question.lower().strip()
        for entry in reversed(self._store["question_cache"]):
            cached_q = entry.content.get("question", "").lower().strip()
            if self._simple_similarity(question_lower, cached_q) >= similarity_threshold:
                entry.uses += 1
                return entry.content.get("response_summary", "")
        return None

    def get_stats(self) -> Dict[str, int]:
        """Retorna estadísticas de la memoria."""
        return {k: len(v) for k, v in self._store.items()}

    def format_memory_context(self, domain: str, complexity: str) -> str:
        """Formatea el contexto de memoria relevante para incluir en prompts."""
        errors = self.retrieve_relevant_errors(domain, top_k=2)
        successes = self.retrieve_similar_successes(domain, complexity, top_k=2)

        parts = []
        if errors:
            parts.append("ERRORES PREVIOS A EVITAR:")
            for e in errors:
                parts.append(f"  - Error: {e.get('error', '')} → Corrección: {e.get('correction', 'ver SQL')}")

        if successes:
            parts.append("PATRONES EXITOSOS SIMILARES:")
            for s in successes:
                parts.append(f"  - [{s.get('domain')}] {s.get('plan_summary', '')}")

        return "\n".join(parts) if parts else ""

    # ──────────────────────────────────────────────────────────────────────────
    # Persistencia
    # ──────────────────────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persiste la memoria en disco."""
        data = {
            k: [e.to_dict() for e in v]
            for k, v in self._store.items()
        }
        try:
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Memory] Error guardando memoria: {e}")

    def _load(self) -> None:
        """Carga la memoria desde disco si existe."""
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key, entries in data.items():
                if key in self._store:
                    self._store[key] = [MemoryEntry.from_dict(e) for e in entries]
        except Exception as e:
            print(f"[Memory] Error cargando memoria: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Internos
    # ──────────────────────────────────────────────────────────────────────────

    def _add(self, entry_type: str, content: Dict) -> None:
        """Agrega una entrada y mantiene el límite."""
        entry = MemoryEntry(entry_type, content)
        self._store[entry_type].append(entry)
        # Mantener límite FIFO
        if len(self._store[entry_type]) > self.MAX_ENTRIES_PER_TYPE:
            self._store[entry_type] = self._store[entry_type][-self.MAX_ENTRIES_PER_TYPE:]
        # Auto-guardar cada 10 entradas
        total = sum(len(v) for v in self._store.values())
        if total % 10 == 0:
            self.save()

    @staticmethod
    def _simple_similarity(a: str, b: str) -> float:
        """Similitud simple basada en tokens comunes (no semántica)."""
        if not a or not b:
            return 0
        tokens_a = set(a.split())
        tokens_b = set(b.split())
        if not tokens_a or not tokens_b:
            return 0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union) * 100
