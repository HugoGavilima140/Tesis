"""
agente/agents/table_retrieval.py — Table Retrieval Agent.

Inspirado en FollowTable. Responsabilidades:
  - Dado un paso del plan, identificar las tablas PostgreSQL relevantes.
  - Justificar por qué cada tabla es necesaria.
  - Especificar las columnas clave a usar.
  - Identificar los JOINs necesarios.
  - Eliminar tablas irrelevantes para evitar alucinaciones SQL.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import (
    LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES,
    PAYNOVA_TABLES, PAYNOVA_BUSINESS_RULES, TOP_K_TABLES,
)
from agente.agents.planner import PlanStep


def _get_llm(temperature: float = 0.0, max_tokens: int = 768):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=temperature, max_tokens=max_tokens,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class TableSelection:
    """Resultado del Table Retrieval Agent para un paso del plan."""
    step_number: int
    selected_tables: List[str]            # tabla.schema completo
    table_justifications: Dict[str, str]  # tabla -> por qué se usa
    key_columns: Dict[str, List[str]]     # tabla -> columnas relevantes
    join_hints: List[str]                 # descripción de JOINs necesarios
    reasoning: str


# Catálogo de tablas formateado para el prompt
def _format_table_catalog() -> str:
    lines = []
    for table_name, info in PAYNOVA_TABLES.items():
        cols = ", ".join(info["key_columns"])
        domains = ", ".join(info["domains"])
        view_note = " [VISTA]" if info.get("is_view") else ""
        lines.append(
            f"- {table_name}{view_note}: {info['description']}\n"
            f"  Columnas clave: {cols}\n"
            f"  Dominios: {domains}"
        )
    return "\n".join(lines)


TABLE_CATALOG_TEXT = _format_table_catalog()

JOIN_KEYS = """
JOINs CLAVE del modelo PayNova:
- transacciones ↔ merchants: transacciones.merchant_id = merchants.merchant_id
- transacciones ↔ usuarios: transacciones.usuario_origen_id = usuarios.usuario_id
- transacciones ↔ fraude: transacciones.transaccion_id = fraude.transaccion_id
- merchants ↔ segmentacion_merchants: merchants.merchant_id = segmentacion_merchants.merchant_id
- merchants ↔ account_managers: merchants.coordinador_id = account_managers.manager_id
- merchants ↔ integraciones_merchant: merchants.merchant_id = integraciones_merchant.merchant_id
- merchants ↔ payouts: merchants.merchant_id = payouts.merchant_id
- merchants ↔ notificaciones: merchants.merchant_id = notificaciones.merchant_id
- usuarios ↔ segmentacion: usuarios.usuario_id = segmentacion.usuario_id
"""

SYSTEM_PROMPT = f"""Eres un experto en el modelo de datos de PayNova S.A.
Tu tarea es identificar exactamente qué tablas y columnas se necesitan para un paso de análisis.

CATÁLOGO DE TABLAS DISPONIBLES:
{TABLE_CATALOG_TEXT}

{JOIN_KEYS}

{PAYNOVA_BUSINESS_RULES}

Responde en este FORMATO EXACTO:
SELECTED_TABLES: <tabla1, tabla2, ...>
JUSTIFICATION_tabla1: <por qué se necesita esta tabla>
JUSTIFICATION_tabla2: <por qué se necesita esta tabla>
COLUMNS_tabla1: <col1, col2, col3>
COLUMNS_tabla2: <col1, col2>
JOIN_HINTS: <descripción de los JOINs necesarios, o NONE si una sola tabla>
REASONING: <razonamiento general de 1-2 líneas>

Usa solo tablas del catálogo. Sé preciso y mínimo (no incluyas tablas innecesarias)."""


class TableRetrievalAgent:
    """
    Selecciona las tablas relevantes para un paso del plan de análisis.

    Usa el catálogo de tablas de PayNova + LLM para determinar qué
    tablas y columnas son necesarias para ejecutar cada paso del plan.
    """

    def __init__(self):
        self.llm = _get_llm(temperature=0.0, max_tokens=768)

    def select_tables(
        self,
        step: PlanStep,
        question: str,
        previous_results_summary: Optional[str] = None,
    ) -> TableSelection:
        """
        Selecciona tablas para el paso dado.

        Args:
            step:                     Paso del plan a ejecutar.
            question:                 Pregunta original del usuario.
            previous_results_summary: Resumen de resultados de pasos anteriores.

        Returns:
            TableSelection con tablas, columnas y JOINs.
        """
        # Si el plan ya dio pistas de tablas, usarlas como contexto adicional
        hint_note = ""
        if step.tables_hint:
            hint_note = f"\nEl plan sugiere estas tablas: {', '.join(step.tables_hint)}"

        prev_note = ""
        if previous_results_summary:
            prev_note = f"\nResultados previos disponibles:\n{previous_results_summary}"

        prompt = (
            f"Pregunta original: {question}\n\n"
            f"Paso actual (#{step.step_number}): {step.description}\n"
            f"Objetivo: {step.objective}\n"
            f"{hint_note}{prev_note}\n\n"
            f"¿Qué tablas y columnas se necesitan para este paso?"
        )

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = self.llm.invoke(messages)
            return self._parse(response.content, step.step_number)
        except Exception as e:
            return self._fallback(step)

    def _parse(self, text: str, step_num: int) -> TableSelection:
        """Parsea la respuesta del LLM."""
        lines = text.split("\n")

        def get(marker: str, default: str = "") -> str:
            for line in lines:
                s = line.strip()
                if s.startswith(marker):
                    return s.split(":", 1)[1].strip() if ":" in s else default
            return default

        # Tablas seleccionadas
        tables_raw = get("SELECTED_TABLES:", "")
        tables = [t.strip() for t in tables_raw.split(",") if t.strip()]

        # Validar que las tablas existen en el catálogo
        valid_tables = []
        for t in tables:
            # Buscar coincidencia parcial en el catálogo
            matched = next((k for k in PAYNOVA_TABLES if k == t or k.endswith(f".{t}") or t in k), None)
            if matched:
                valid_tables.append(matched)
            elif t:  # Mantener aunque no se encuentre, el LLM puede haberlo nombrado bien
                valid_tables.append(t)

        # Justificaciones y columnas por tabla
        justifications = {}
        key_cols = {}
        for table in valid_tables:
            short_name = table.split(".")[-1]
            just = get(f"JUSTIFICATION_{table}:") or get(f"JUSTIFICATION_{short_name}:", f"Necesaria para {step_num}")
            cols_raw = get(f"COLUMNS_{table}:") or get(f"COLUMNS_{short_name}:", "")
            justifications[table] = just
            key_cols[table] = [c.strip() for c in cols_raw.split(",") if c.strip()]

        join_hints_raw = get("JOIN_HINTS:", "")
        join_hints = [] if join_hints_raw.upper() == "NONE" else [join_hints_raw]

        return TableSelection(
            step_number=step_num,
            selected_tables=valid_tables or ["transacciones.transacciones"],
            table_justifications=justifications,
            key_columns=key_cols,
            join_hints=join_hints,
            reasoning=get("REASONING:", ""),
        )

    def _fallback(self, step: PlanStep) -> TableSelection:
        tables = step.tables_hint or ["transacciones.transacciones"]
        return TableSelection(
            step_number=step.step_number,
            selected_tables=tables,
            table_justifications={t: "Fallback selection" for t in tables},
            key_columns={},
            join_hints=[],
            reasoning="Fallback: LLM error",
        )
