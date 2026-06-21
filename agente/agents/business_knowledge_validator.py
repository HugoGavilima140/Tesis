"""
agente/agents/business_knowledge_validator.py — Mod 1: Business Knowledge Validator.

Determina si la pregunta puede responderse COMPLETAMENTE con la documentacion
empresarial sin necesidad de ejecutar SQL sobre la base de datos.

Casos SUFFICIENT (sin SQL):
  '¿Que es el GMV?', '¿Como se calcula el MDR?', '¿Que significa comercio activo?'

Casos NEEDS_SQL:
  '¿Cual fue el GMV del ultimo trimestre?', '¿Que campanas tuvieron mayor impacto?'
"""

from dataclasses import dataclass
from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES
from agente.agents.intent_analyzer import IntentAnalysis


def _get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=0.0, max_tokens=512,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class KBValidationResult:
    """Resultado de la validacion de suficiencia de la KB."""
    is_sufficient: bool       # True si la KB responde la pregunta sin SQL
    answer: Optional[str]     # Respuesta directa si is_sufficient=True
    reasoning: str            # Por que se tomo la decision
    confidence: str           # high|medium|low


# Palabras clave que indican preguntas definitivas (sin SQL)
_DEFINITION_KEYWORDS = (
    "que es ", "que son ", "como se calcula ", "que significa ",
    "como se define ", "cual es la definicion", "cuales son los tipos",
    "para que sirve ", "en que consiste ", "que tipo de ", "como funciona ",
    "explica ", "describe ", "define ",
)


SYSTEM_PROMPT = """Eres el validador de conocimiento empresarial del agente PayNova.
Tu tarea: determinar si la pregunta puede responderse SOLO con la documentacion
empresarial, o si REQUIERE consultar la base de datos con SQL.

RESPONDE SUFFICIENT si la pregunta pide:
- Definicion de conceptos (GMV, MDR, comercio activo, payout, etc.)
- Explicacion de reglas de negocio (como se calcula X, que significa Y)
- Descripcion de procesos operativos o taxonomias
- Informacion estatica del modelo de negocio

RESPONDE NEEDS_SQL si la pregunta pide:
- Valores numericos historicos (cuanto fue X en periodo Y)
- Rankings, comparaciones o tendencias entre entidades
- Analisis de comportamiento, segmentacion o correlaciones
- Cualquier dato que dependa de registros actuales en la BD

Responde EXACTAMENTE en este formato:
DECISION: <SUFFICIENT|NEEDS_SQL>
CONFIDENCE: <high|medium|low>
ANSWER: <respuesta usando la KB si SUFFICIENT, o NONE si NEEDS_SQL>
REASONING: <por que tomaste esta decision, 1-2 lineas>"""


class BusinessKnowledgeValidator:
    """
    Valida si la KB es suficiente para responder sin necesidad de SQL.

    Mod 1: Se ejecuta despues de retrieve_knowledge y antes de plan_analysis.
    Si is_sufficient=True, el pipeline omite plan→SQL y va directo a synthesis.
    """

    def __init__(self):
        self.llm = _get_llm()

    def validate(
        self,
        question: str,
        intent: IntentAnalysis,
        kb_context: str,
    ) -> KBValidationResult:
        """
        Evalua si la KB es suficiente para responder la pregunta.

        Args:
            question:   Pregunta del usuario.
            intent:     Analisis de intencion (ya tiene complejidad y tipo).
            kb_context: Contexto recuperado de la knowledge base.

        Returns:
            KBValidationResult indicando si la KB es suficiente y la respuesta.
        """
        question_lower = question.lower().strip()

        # Heuristica rapida: preguntas claramente definitorias -> sin LLM
        if any(kw in question_lower for kw in _DEFINITION_KEYWORDS):
            return KBValidationResult(
                is_sufficient=True,
                answer=self._extract_kb_answer(kb_context),
                reasoning="Pregunta definitoria resuelta con documentacion empresarial.",
                confidence="high",
            )

        # Heuristica: preguntas analiticas evidentes -> sin LLM
        analytic_keywords = ("cual fue", "cuanto", "cuantos", "cuantas", "ranking",
                             "top", "mayor", "menor", "tendencia", "comparar", "comparacion",
                             "mejor", "peor", "mas alto", "mas bajo", "variacion",
                             "evolucion", "historico", "mes pasado", "trimestre", "año")
        if any(kw in question_lower for kw in analytic_keywords):
            return KBValidationResult(
                is_sufficient=False,
                answer=None,
                reasoning="Pregunta analitica que requiere consultar la base de datos.",
                confidence="high",
            )

        # Casos ambiguos: llamar al LLM
        prompt = (
            f"Pregunta: {question}\n\n"
            f"Tipo: {intent.query_type} | Complejidad: {intent.complexity}\n\n"
            f"Documentacion disponible (extracto):\n{kb_context[:2000]}\n\n"
            f"¿Puede responderse SOLO con la documentacion anterior, sin consultar BD?"
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            return self._parse(response.content, kb_context)
        except Exception as e:
            # En error, asumir que necesita SQL (conservador)
            return KBValidationResult(
                is_sufficient=False,
                answer=None,
                reasoning=f"Error en validacion KB: {e}",
                confidence="low",
            )

    @staticmethod
    def _extract_kb_answer(kb_context: str) -> str:
        """Extrae la respuesta util del contexto KB recuperado."""
        if not kb_context:
            return "Informacion no disponible en la documentacion."
        # Retornar el contexto KB como base de la respuesta
        return f"Segun la documentacion empresarial de PayNova:\n\n{kb_context[:3000]}"

    @staticmethod
    def _parse(text: str, kb_context: str) -> KBValidationResult:
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                if line.strip().startswith(marker):
                    return line.split(":", 1)[1].strip() if ":" in line else default
            return default

        decision    = get("DECISION:", "NEEDS_SQL").upper()
        confidence  = get("CONFIDENCE:", "medium").lower()
        answer_raw  = get("ANSWER:", "NONE")
        reasoning   = get("REASONING:", "Sin razonamiento disponible.")

        is_sufficient = decision == "SUFFICIENT"
        if is_sufficient and (not answer_raw or answer_raw.upper() == "NONE"):
            answer = BusinessKnowledgeValidator._extract_kb_answer(kb_context)
        elif is_sufficient:
            answer = answer_raw
        else:
            answer = None

        return KBValidationResult(
            is_sufficient=is_sufficient,
            answer=answer,
            reasoning=reasoning,
            confidence=confidence,
        )
