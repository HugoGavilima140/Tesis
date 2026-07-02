"""
agente/agents/dashboard_validator.py — Mod 10: Dashboard Context Validator.

Determina si una pregunta corresponde a informacion mostrada en alguno de los
dashboards ejecutivos de Power BI (carpeta `Dashboard Ejecutivos/`, formato PBIP),
y en ese caso:

  1. Identifica que dashboard(s)/pagina(s)/medidas son relevantes.
  2. Reformula la pregunta en terminos del modelo de datos real (tablas, columnas,
     medidas DAX) para que el Planner y el SQL Reasoning Agent generen SQL
     consistente con lo que el dashboard efectivamente muestra.

A diferencia de Mod 1 (KB Validator), esta etapa NUNCA salta el pipeline SQL:
los dashboards muestran datos vivos, asi que una pregunta relacionada a un
dashboard siempre debe resolverse consultando la base de datos. Su salida es
contexto adicional que se inyecta junto al `kb_context` ya existente.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES
from agente.agents.intent_analyzer import IntentAnalysis
from agente.knowledge.dashboard_catalog import get_dashboard_catalog, CatalogMeasure


def _get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        # Nota: el modelo configurado (DeepSeek reasoning) consume ~1000-1800
        # tokens en razonamiento interno antes de emitir el texto final; con
        # limites bajos (p.ej. 512-1536) a veces devuelve content="" (finish_reason=length).
        temperature=0.0, max_tokens=3000,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


_MAX_MEASURES_IN_CONTEXT = 5
_MAX_EXPRESSION_CHARS = 220
_MAX_CONTEXT_CHARS = 900


@dataclass
class DashboardContextResult:
    """Resultado de la validacion de contexto de dashboards (Mod 10)."""
    is_dashboard_relevant: bool
    matched_dashboards: List[str] = field(default_factory=list)
    matched_pages: List[str] = field(default_factory=list)
    relevant_measures: List[CatalogMeasure] = field(default_factory=list)
    relevant_tables: List[str] = field(default_factory=list)   # schema.table de PostgreSQL
    reframed_question: str = ""
    context_text: str = ""     # listo para inyectar en el contexto de Planner/SQLReasoning
    reasoning: str = ""


SYSTEM_PROMPT = """Eres el validador de contexto de dashboards Power BI del agente PayNova.

Se te da una pregunta de negocio y una lista de CANDIDATOS (medidas, columnas y
visuales de los dashboards ejecutivos) que coincidieron por texto con la pregunta.

Tu tarea:
1. Decidir si la pregunta realmente corresponde a informacion que se visualiza en
   esos dashboards (no solo una coincidencia superficial de palabras).
2. Si es relevante, seleccionar los NOMBRES EXACTOS de las medidas candidatas que
   aplican (tal como aparecen en la lista).
3. Reformular la pregunta en terminos del modelo de datos: que medida/columna/tabla
   real habria que consultar para responderla, usando los nombres reales.

Responde EXACTAMENTE en este formato:
RELEVANT: <YES|NO>
DASHBOARDS: <dashboards relevantes separados por coma, o NONE>
MEASURES: <SOLO el nombre corto de cada medida relevante, sin prefijos "[measure]" ni
  parentesis con metadatos, separados por coma; ej: "GMV, Payouts Rechazados". O NONE.>
REFRAMED_QUESTION: <pregunta reformulada en terminos de datos reales, o NONE>
REASONING: <1-2 lineas explicando la decision>"""


class DashboardContextAgent:
    """
    Mod 10: valida si la pregunta se relaciona con algun dashboard Power BI y,
    de ser asi, produce contexto de datos (medidas DAX, tablas SQL reales,
    pregunta reformulada) para guiar el resto del pipeline.
    """

    def __init__(self):
        self.llm = _get_llm()
        self.catalog = get_dashboard_catalog()

    def analyze(self, question: str, intent: IntentAnalysis) -> DashboardContextResult:
        hits = self.catalog.search(question)
        if not hits:
            return DashboardContextResult(
                is_dashboard_relevant=False,
                reasoning="Sin coincidencias con medidas, columnas o visuales de los dashboards conocidos.",
            )

        prompt = self._build_prompt(question, hits)
        try:
            response = self.llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            return self._parse(response.content)
        except Exception as e:
            return DashboardContextResult(
                is_dashboard_relevant=False,
                reasoning=f"Error en validacion de dashboard: {e}",
            )

    @staticmethod
    def _build_prompt(question: str, hits) -> str:
        lines = [f"Pregunta: {question}", "", "Candidatos encontrados en los dashboards:"]
        for h in hits:
            lines.append(f"- [{h.kind}] {h.label} (dashboard={h.dashboard}, {h.detail})")
        lines.append("")
        lines.append("Evalua relevancia, selecciona medidas y reformula la pregunta en terminos de datos:")
        return "\n".join(lines)

    @staticmethod
    def _clean_measure_name(raw: str) -> str:
        """Normaliza un nombre de medida devuelto por el LLM: quita prefijos tipo
        '[measure]' y cualquier metadato entre parentesis que el modelo haya
        copiado del listado de candidatos (defensivo ante formato imperfecto)."""
        name = raw.strip()
        for prefix in ("[measure]", "[column]", "[visual]"):
            if name.lower().startswith(prefix):
                name = name[len(prefix):].strip()
        if "(" in name:
            name = name.split("(", 1)[0].strip()
        return name

    def _parse(self, text: str) -> DashboardContextResult:
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                s = line.strip()
                if s.startswith(marker):
                    return s.split(":", 1)[1].strip() if ":" in s else default
            return default

        relevant = get("RELEVANT:", "NO").upper() == "YES"
        if not relevant:
            return DashboardContextResult(
                is_dashboard_relevant=False,
                reasoning=get("REASONING:", "No relevante segun el LLM."),
            )

        dashboards_raw = get("DASHBOARDS:", "NONE")
        dashboards = [d.strip() for d in dashboards_raw.split(",") if d.strip() and d.upper() != "NONE"]

        measures_raw = get("MEASURES:", "NONE")
        measure_names = [
            self._clean_measure_name(m) for m in measures_raw.split(",")
            if m.strip() and m.upper() != "NONE"
        ]
        measure_names = [m for m in measure_names if m]

        reframed = get("REFRAMED_QUESTION:", "")
        if reframed.upper() == "NONE":
            reframed = ""
        reasoning = get("REASONING:", "")

        measures = self.catalog.measures_by_name(measure_names)
        tables = sorted({t for m in measures for t in m.sql_tables})

        context_text = self._build_context_text(dashboards, reframed, measures, tables)

        return DashboardContextResult(
            is_dashboard_relevant=True,
            matched_dashboards=dashboards,
            matched_pages=[],
            relevant_measures=measures,
            relevant_tables=tables,
            reframed_question=reframed,
            context_text=context_text,
            reasoning=reasoning,
        )

    @staticmethod
    def _build_context_text(
        dashboards: List[str],
        reframed_question: str,
        measures: List[CatalogMeasure],
        tables: List[str],
    ) -> str:
        parts = []
        if dashboards:
            parts.append(f"[DASHBOARD] Pregunta relacionada con el/los dashboard(s): {', '.join(dashboards)}.")
        if reframed_question:
            parts.append(f"Reformulacion en terminos de datos: {reframed_question}")
        if measures:
            parts.append("Medidas ya definidas en el modelo Power BI (usar como referencia exacta de la formula):")
            for m in measures[:_MAX_MEASURES_IN_CONTEXT]:
                expr = m.expression[:_MAX_EXPRESSION_CHARS]
                table_note = (
                    f" [tabla SQL: {', '.join(m.sql_tables)}]" if m.sql_tables
                    else " [sin tabla SQL directa]"
                )
                parts.append(f"  - {m.name} = {expr}{table_note}")
        if tables:
            parts.append(f"Tablas SQL reales involucradas segun el dashboard: {', '.join(tables)}")

        text = "\n".join(parts)
        return text[:_MAX_CONTEXT_CHARS]
