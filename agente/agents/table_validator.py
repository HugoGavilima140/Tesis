"""
agente/agents/table_validator.py — Mod 4: Table Coverage Validator.

Verifica que las tablas seleccionadas por el TableRetrievalAgent cubran todos
los requisitos del paso antes de generar SQL. Evita errores por tablas
insuficientes o semanticamente incorrectas.

Si la validacion falla y quedan intentos disponibles, el pipeline vuelve a
ejecutar select_tables con el contexto del problema. Tras MAX_TABLE_RETRIES
intentos fallidos, continua de todas formas (modo degradado).
"""

from dataclasses import dataclass, field
from typing import List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import (
    LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES,
    PAYNOVA_TABLES,
)
from agente.agents.planner import PlanStep
from agente.agents.table_retrieval import TableSelection


def _get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=0.0, max_tokens=512,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class TableValidationResult:
    """Resultado de la validacion de cobertura de tablas."""
    is_valid: bool
    issues: List[str] = field(default_factory=list)
    missing_tables: List[str] = field(default_factory=list)
    reasoning: str = ""


SYSTEM_PROMPT = """Eres el validador de seleccion de tablas del sistema PayNova.
Tu tarea: verificar que las tablas seleccionadas son SUFICIENTES y CORRECTAS
para ejecutar el paso de analisis indicado.

Verifica:
1. ¿Las tablas contienen las columnas necesarias para el objetivo del paso?
2. ¿Faltan tablas para cubrir todas las entidades o metricas requeridas?
3. ¿Las tablas son coherentes con el objetivo del paso?
4. ¿Los JOINs necesarios son posibles con las tablas seleccionadas?

Responde en FORMATO EXACTO:
VALID: <YES|NO>
ISSUES: <problemas separados por |, o NONE>
MISSING_TABLES: <tablas faltantes separadas por coma, o NONE>
REASONING: <razonamiento en 1-2 lineas>"""


class TableValidator:
    """
    Valida que la seleccion de tablas cubre todos los requisitos del paso.

    Mod 4: Se ejecuta entre select_tables y generate_sql.
    Si is_valid=False y hay intentos disponibles, el pipeline reintenta select_tables
    con el contexto de los problemas detectados.
    """

    def __init__(self):
        self.llm = _get_llm()

    def validate(
        self,
        step: PlanStep,
        table_sel: TableSelection,
        question: str,
    ) -> TableValidationResult:
        """
        Valida la cobertura de tablas para el paso dado.

        Args:
            step:      Paso del plan con descripcion, objetivo y hints de tablas.
            table_sel: Seleccion de tablas del TableRetrievalAgent.
            question:  Pregunta original del usuario (contexto adicional).

        Returns:
            TableValidationResult con validez, problemas y tablas faltantes.
        """
        # Verificacion rapida: si todas las tablas del hint estan presentes -> valido
        missing_hints = [t for t in step.tables_hint if t not in table_sel.selected_tables]
        if not missing_hints:
            return TableValidationResult(
                is_valid=True,
                issues=[],
                missing_tables=[],
                reasoning="Todas las tablas sugeridas por el planner estan presentes.",
            )

        # LLM evalua si las tablas seleccionadas son suficientes a pesar de los hints
        tables_desc = "\n".join(
            f"  - {t}: {PAYNOVA_TABLES.get(t, {}).get('description', 'descripcion no disponible')}"
            f" | Columnas: {', '.join(PAYNOVA_TABLES.get(t, {}).get('key_columns', []))}"
            for t in table_sel.selected_tables
        )
        hint_str = ", ".join(step.tables_hint) if step.tables_hint else "ninguna especificada"

        prompt = (
            f"Pregunta: {question}\n\n"
            f"Paso #{step.step_number}: {step.description}\n"
            f"Objetivo: {step.objective}\n"
            f"Tablas sugeridas por el planner: {hint_str}\n\n"
            f"Tablas seleccionadas:\n{tables_desc}\n\n"
            f"¿La seleccion es suficiente para ejecutar el paso correctamente?"
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            return self._parse(response.content, missing_hints)
        except Exception:
            # En error, reportar como invalido si hay hints faltantes
            return TableValidationResult(
                is_valid=len(missing_hints) == 0,
                issues=[f"Tabla sugerida ausente: {t}" for t in missing_hints],
                missing_tables=missing_hints,
                reasoning="Validacion heuristica (LLM error).",
            )

    @staticmethod
    def _parse(text: str, hint_missing: List[str]) -> TableValidationResult:
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                if line.strip().startswith(marker):
                    return line.split(":", 1)[1].strip() if ":" in line else default
            return default

        valid_raw   = get("VALID:", "YES").upper()
        issues_raw  = get("ISSUES:", "NONE")
        missing_raw = get("MISSING_TABLES:", "NONE")
        reasoning   = get("REASONING:", "Validacion completada.")

        is_valid = valid_raw == "YES"
        issues   = ([] if issues_raw.upper() == "NONE"
                    else [i.strip() for i in issues_raw.split("|") if i.strip()])
        missing  = (hint_missing if missing_raw.upper() == "NONE"
                    else [m.strip() for m in missing_raw.split(",") if m.strip()])

        return TableValidationResult(
            is_valid=is_valid,
            issues=issues,
            missing_tables=missing,
            reasoning=reasoning,
        )

    @staticmethod
    def format_retry_hint(result: TableValidationResult) -> str:
        """Formatea la informacion de problemas para el reintento de select_tables."""
        parts = []
        if result.issues:
            parts.append("PROBLEMAS: " + " | ".join(result.issues))
        if result.missing_tables:
            parts.append("TABLAS FALTANTES: " + ", ".join(result.missing_tables))
        return " | ".join(parts) if parts else "Validacion de tablas insuficiente."
