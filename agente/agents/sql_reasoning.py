"""
agente/agents/sql_reasoning.py — SQL Reasoning Agent.

Responsabilidades:
  - Construir SQL PostgreSQL paso a paso con razonamiento explícito.
  - Aplicar las reglas de negocio de PayNova en cada query.
  - Usar SOLO tablas y columnas del catálogo.
  - Generar SQL verificable con CTEs cuando hay múltiples pasos.
  - Incluir comentarios en el SQL para trazabilidad.
"""

import re
from dataclasses import dataclass
from typing import List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import (
    LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES,
    PAYNOVA_BUSINESS_RULES, MAX_RETRIES_SQL,
)
from agente.agents.planner import PlanStep
from agente.agents.table_retrieval import TableSelection


def _get_llm(temperature: float = 0.0, max_tokens: int = 1024):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=temperature, max_tokens=max_tokens,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class GeneratedSQL:
    """SQL generado para un paso del plan."""
    step_number: int
    sql: str
    reasoning: str           # cómo se llegó al SQL
    confidence: str          # high|medium|low
    is_valid_syntax: bool = True
    error: Optional[str] = None
    corrections: List[str] = None

    def __post_init__(self):
        if self.corrections is None:
            self.corrections = []


SYSTEM_PROMPT = """Eres un experto en PostgreSQL generando SQL para el sistema financiero PayNova S.A.

""" + PAYNOVA_BUSINESS_RULES + """

ESQUEMAS DE BASE DE DATOS:
- Esquema "produccion": usuarios, merchants, segmentacion_merchants, account_managers,
  integraciones_merchant, payouts, notificaciones, fraude, segmentacion
- Esquema "transacciones": transacciones (tabla principal, 24M+ filas)

REGLAS DE SQL:
1. SIEMPRE calificar tablas con schema: produccion.merchants, transacciones.transacciones
2. Para métricas de negocio: filtrar estado = 'completada' en transacciones
3. Para filtros de mes usar: year_month = 'YYYY-MM' (NO DATE_TRUNC)
4. Las columnas ingreso_comision, costo_operativo, margen, monto_neto, costo_total son GENERATED — usar directamente
5. Usar ROUND(..., 2) para valores monetarios
6. Usar NULLIF para evitar divisiones por cero
7. Usar CTEs (WITH) para queries complejas multi-paso
8. Limitar resultados: LIMIT 20 para listas de detalle
9. Solo SELECT — NUNCA INSERT/UPDATE/DELETE
10. Añadir alias descriptivos a columnas calculadas

Responde en este formato:
SQL_REASONING: <cómo construiste el SQL paso a paso>
CONFIDENCE: <high|medium|low>
SQL:
<el SQL aquí, sin markdown>"""


class SQLReasoningAgent:
    """
    Genera SQL PostgreSQL para un paso del plan de análisis.

    Características:
    - Razonamiento explícito antes de generar el SQL.
    - Respeta reglas de negocio PayNova.
    - Auto-corrección con reintentos.
    - Usa columnas GENERATED directamente.
    """

    def __init__(self):
        self.llm = _get_llm(temperature=0.0, max_tokens=1024)
        self.correction_llm = _get_llm(temperature=0.1, max_tokens=1024)

    def generate(
        self,
        step: PlanStep,
        table_selection: TableSelection,
        question: str,
        previous_results_summary: Optional[str] = None,
        kb_context: Optional[str] = None,
    ) -> GeneratedSQL:
        """
        Genera SQL para un paso del plan.

        Args:
            step:                      Paso del plan a ejecutar.
            table_selection:           Tablas seleccionadas por el Table Retrieval Agent.
            question:                  Pregunta original.
            previous_results_summary:  Resultados de pasos anteriores.
            kb_context:                Contexto de negocio de la KB.

        Returns:
            GeneratedSQL con el SQL generado.
        """
        prompt = self._build_prompt(step, table_selection, question, previous_results_summary, kb_context)

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = self.llm.invoke(messages)
            return self._parse_response(response.content, step.step_number)
        except Exception as e:
            return GeneratedSQL(
                step_number=step.step_number,
                sql="",
                reasoning=f"LLM error: {e}",
                confidence="low",
                is_valid_syntax=False,
                error=str(e),
            )

    def correct(
        self,
        sql: GeneratedSQL,
        error_message: str,
        table_selection: TableSelection,
    ) -> GeneratedSQL:
        """
        Intenta corregir un SQL que produjo error.

        Returns:
            SQL corregido o el original si la corrección falla.
        """
        prompt = (
            f"SQL con error:\n{sql.sql}\n\n"
            f"Error: {error_message}\n\n"
            f"Tablas disponibles: {', '.join(table_selection.selected_tables)}\n\n"
            f"Columnas por tabla:\n"
        )
        for table, cols in table_selection.key_columns.items():
            prompt += f"  {table}: {', '.join(cols)}\n"
        prompt += "\nCorrige el SQL respetando las reglas de negocio de PayNova."

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = self.correction_llm.invoke(messages)
            corrected = self._parse_response(response.content, sql.step_number)
            corrected.corrections = sql.corrections + [f"Corrección: {error_message[:100]}"]
            return corrected
        except Exception as e:
            sql.error = str(e)
            return sql

    def _build_prompt(
        self,
        step: PlanStep,
        table_sel: TableSelection,
        question: str,
        prev_results: Optional[str],
        kb_context: Optional[str],
    ) -> str:
        # Información de tablas y columnas
        tables_info = ""
        for table in table_sel.selected_tables:
            cols = table_sel.key_columns.get(table, [])
            just = table_sel.table_justifications.get(table, "")
            tables_info += f"\n  {table}: {cols}\n  Razón: {just}"

        join_info = "\n".join(table_sel.join_hints) if table_sel.join_hints else "Sin JOINs"

        prev_info = f"\nResultados de pasos anteriores:\n{prev_results}" if prev_results else ""
        kb_info   = f"\nContexto de negocio relevante:\n{kb_context[:800]}" if kb_context else ""

        return (
            f"Pregunta: {question}\n\n"
            f"Paso #{step.step_number}: {step.description}\n"
            f"Objetivo: {step.objective}\n"
            f"Tablas a usar:{tables_info}\n\n"
            f"JOINs sugeridos: {join_info}"
            f"{prev_info}{kb_info}\n\n"
            f"Genera el SQL PostgreSQL para este paso:"
        )

    def _parse_response(self, text: str, step_num: int) -> GeneratedSQL:
        """Extrae SQL y razonamiento de la respuesta del LLM."""
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                if line.strip().startswith(marker):
                    return line.split(":", 1)[1].strip() if ":" in line else default
            return default

        reasoning   = get("SQL_REASONING:", "No especificado")
        confidence  = get("CONFIDENCE:", "medium").lower()

        # Extraer SQL
        sql = self._extract_sql(text)

        return GeneratedSQL(
            step_number=step_num,
            sql=sql,
            reasoning=reasoning,
            confidence=confidence,
            is_valid_syntax=bool(sql),
        )

    @staticmethod
    def _extract_sql(text: str) -> str:
        """Extrae el SQL limpio del texto del LLM."""
        # Buscar bloque después de "SQL:"
        if "SQL:" in text:
            sql_part = text.split("SQL:", 1)[1].strip()
        else:
            sql_part = text

        # Eliminar markdown
        sql_part = re.sub(r"```sql\s*", "", sql_part)
        sql_part = re.sub(r"```\s*", "", sql_part)

        # Tomar las líneas que parecen SQL (desde SELECT hasta el primer ;)
        lines = sql_part.strip().split("\n")
        sql_lines = []
        in_sql = False

        for line in lines:
            upper = line.strip().upper()
            if upper.startswith(("SELECT", "WITH", "--")):
                in_sql = True
            if in_sql:
                sql_lines.append(line)
                if ";" in line:
                    break

        if sql_lines:
            result = "\n".join(sql_lines).strip()
            if not result.endswith(";"):
                result += ";"
            return result

        # Fallback: devolver todo como SQL
        cleaned = sql_part.strip()
        if cleaned and not cleaned.endswith(";"):
            cleaned += ";"
        return cleaned
