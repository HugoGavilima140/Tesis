"""
agente/agents/intent_analyzer.py — Intent Analyzer Agent.

Responsabilidades:
  - Clasificar la pregunta en dominio y tipo de análisis.
  - Detectar entidades, métricas y horizonte temporal involucrados.
  - Determinar el nivel de complejidad (simple / multi-hop / estratégico).
  - Detectar ambigüedades que requieren clarificación.

La clasificación guía al Planner y al Table Retrieval Agent.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES


def _get_llm(temperature: float = 0.0, max_tokens: int = 512):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=LLM_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class IntentAnalysis:
    """Resultado del análisis de intención."""
    original_question: str

    # Clasificación
    domain: str              # finanzas|marketing|operaciones|riesgo|ejecutivo|estrategia|general
    query_type: str          # informacion|operacional|financiero|marketing|fraude|ejecutivo|estrategico
    complexity: str          # simple|multihop|estrategico

    # Entidades y métricas detectadas
    entities: List[str]      # usuarios|comercios|transacciones|payouts|notificaciones|etc.
    metrics: List[str]       # gmv|mdr|margen|tasa_aprobacion|tasa_fraude|etc.
    time_horizon: str        # diario|semanal|mensual|trimestral|anual|historico|sin_especificar

    # Ambigüedad
    is_ambiguous: bool
    ambiguity_reason: str

    # Razonamiento
    reasoning: str

    # Número estimado de pasos SQL
    estimated_sql_steps: int = 1


SYSTEM_PROMPT = """Eres un analista de inteligencia empresarial experto en fintech.
Tu tarea es analizar preguntas de negocio sobre PayNova S.A. y clasificar su intención.

PayNova es una plataforma fintech con comercios, usuarios, transacciones, payouts, notificaciones y detección de fraude.
Ingresos principales = MDR (1.8% del GMV de transacciones completadas).

Responde EXACTAMENTE en este formato (sin texto extra):
DOMAIN: <finanzas|marketing|operaciones|riesgo|ejecutivo|estrategia|general>
QUERY_TYPE: <informacion|operacional|financiero|marketing|fraude|ejecutivo|estrategico>
COMPLEXITY: <simple|multihop|estrategico>
ENTITIES: <lista separada por comas de: usuarios,comercios,transacciones,payouts,notificaciones,fraude,campanas,account_managers,segmentacion>
METRICS: <lista separada por comas de métricas: gmv,mdr,margen,tasa_aprobacion,tasa_fraude,tasa_reactivacion,costo_notificaciones,tasa_exito_payouts,comercios_activos,usuarios_activos,etc.>
TIME_HORIZON: <diario|semanal|mensual|trimestral|anual|historico|sin_especificar>
IS_AMBIGUOUS: <true|false>
AMBIGUITY_REASON: <explicación si es ambigua, o "ninguna">
ESTIMATED_SQL_STEPS: <1-5>
REASONING: <razonamiento conciso de 1-3 líneas>

Reglas de complejidad:
- simple: una sola métrica, una tabla, un período claro
- multihop: requiere comparar períodos, cruzar múltiples tablas, calcular variaciones o rankings
- estrategico: requiere análisis causal, correlaciones, segmentación compleja o múltiples hipótesis"""


class IntentAnalyzerAgent:
    """Analiza la intención de negocio de una pregunta."""

    def __init__(self):
        self.llm = _get_llm(temperature=0.0, max_tokens=512)

    def analyze(self, question: str) -> IntentAnalysis:
        """
        Analiza una pregunta y devuelve su IntentAnalysis.

        Args:
            question: Pregunta en lenguaje natural (español o inglés).

        Returns:
            IntentAnalysis con clasificación completa.
        """
        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=f"Pregunta: {question}"),
            ]
            response = self.llm.invoke(messages)
            return self._parse(response.content, question)
        except Exception as e:
            return self._fallback(question, str(e))

    def _parse(self, text: str, question: str) -> IntentAnalysis:
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                if line.strip().startswith(marker):
                    return line.split(":", 1)[1].strip()
            return default

        def get_list(marker: str) -> List[str]:
            raw = get(marker, "")
            if not raw or raw.upper() == "NONE":
                return []
            return [x.strip().lower() for x in raw.split(",") if x.strip()]

        try:
            steps = int(get("ESTIMATED_SQL_STEPS:", "1"))
        except ValueError:
            steps = 1

        return IntentAnalysis(
            original_question=question,
            domain=get("DOMAIN:", "general"),
            query_type=get("QUERY_TYPE:", "informacion"),
            complexity=get("COMPLEXITY:", "simple"),
            entities=get_list("ENTITIES:"),
            metrics=get_list("METRICS:"),
            time_horizon=get("TIME_HORIZON:", "sin_especificar"),
            is_ambiguous=get("IS_AMBIGUOUS:", "false").lower() == "true",
            ambiguity_reason=get("AMBIGUITY_REASON:", "ninguna"),
            estimated_sql_steps=steps,
            reasoning=get("REASONING:", ""),
        )

    def _fallback(self, question: str, error: str) -> IntentAnalysis:
        return IntentAnalysis(
            original_question=question,
            domain="general",
            query_type="informacion",
            complexity="simple",
            entities=[],
            metrics=[],
            time_horizon="sin_especificar",
            is_ambiguous=False,
            ambiguity_reason="",
            estimated_sql_steps=1,
            reasoning=f"Fallback due to LLM error: {error}",
        )
