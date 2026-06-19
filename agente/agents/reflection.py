"""
agente/agents/reflection.py — Reflection Agent.

Componente OBLIGATORIO del sistema. Antes de responder, el agente reflexiona:
  1. ¿La query respondió realmente la pregunta?
  2. ¿La métrica utilizada es correcta?
  3. ¿Existe otra interpretación posible?
  4. ¿Los resultados son coherentes con los rangos esperados?
  5. ¿Las reglas de negocio fueron respetadas?
  6. ¿Existen contradicciones entre pasos?
  7. ¿Falta información para responder?

Si detecta errores → genera un plan de corrección.
Calcula el Confidence Score final (0-100).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import (
    LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES,
    PAYNOVA_BUSINESS_RULES, CONFIDENCE_THRESHOLDS,
)
from agente.agents.execution import StepResult
from agente.agents.intent_analyzer import IntentAnalysis


def _get_llm(temperature: float = 0.0, max_tokens: int = 1024):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=temperature, max_tokens=max_tokens,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class ReflectionResult:
    """Resultado del proceso de reflexión."""
    question_answered: bool        # ¿La pregunta fue realmente respondida?
    confidence_score: int          # 0-100
    confidence_level: str          # normal|limited|partial|clarification
    issues_found: List[str]        # problemas detectados
    corrections_needed: List[str]  # correcciones requeridas
    reasoning: str                 # razonamiento de la reflexión
    requires_retry: bool           # ¿necesita reintentar?
    retry_hint: str                # qué cambiar si reintenta
    business_rules_ok: bool        # ¿se respetaron las reglas de negocio?
    data_quality_ok: bool          # ¿los datos tienen sentido?


SYSTEM_PROMPT = """Eres el agente de reflexión crítica del sistema de análisis de PayNova S.A.
Tu función es revisar si el análisis realizado responde correctamente la pregunta del usuario.

""" + PAYNOVA_BUSINESS_RULES + """

RANGOS ESPERADOS de métricas PayNova:
- GMV mensual: $10M – $500M
- MDR rate efectivo: 1.5% – 2.0%
- Tasa de aprobación: 90% – 99.5%
- Tasa de fraude: 0.1% – 5% (el dataset IBM tiene ~2.5% sintético)
- Ticket promedio: $10 – $500
- Transacciones/mes: 200,000 – 2,000,000
- Comercios activos: 1,500 – 3,000

Preguntas de reflexión que DEBES responder:
1. ¿La consulta SQL obtiene exactamente lo que se preguntó?
2. ¿Las métricas usadas son las correctas (ej: ingresos = SUM(ingreso_comision), NO SUM(monto))?
3. ¿Los valores están en rangos esperados para PayNova?
4. ¿Se filtró por estado='completada' para transacciones?
5. ¿Hay resultados vacíos que indiquen un filtro incorrecto?
6. ¿Las reglas de negocio (MDR, margen GENERATED) se respetaron?
7. ¿La pregunta tiene múltiples interpretaciones no consideradas?

Responde en este FORMATO EXACTO:
QUESTION_ANSWERED: <YES|NO|PARTIAL>
CONFIDENCE_SCORE: <0-100>
BUSINESS_RULES_OK: <YES|NO>
DATA_QUALITY_OK: <YES|NO>
ISSUES: <lista separada por | de problemas, o NONE>
CORRECTIONS: <lista separada por | de correcciones necesarias, o NONE>
REQUIRES_RETRY: <YES|NO>
RETRY_HINT: <qué cambiar si reintenta, o NONE>
REASONING: <reflexión concisa de 2-4 líneas>"""


class ReflectionAgent:
    """
    Agente de reflexión crítica sobre los resultados del análisis.

    Evalúa si los resultados son correctos, coherentes y suficientes
    para responder la pregunta de negocio del usuario.
    """

    def __init__(self):
        self.llm = _get_llm(temperature=0.0, max_tokens=1024)

    def reflect(
        self,
        question: str,
        intent: IntentAnalysis,
        step_results: List[StepResult],
        attempt: int = 1,
    ) -> ReflectionResult:
        """
        Reflexiona sobre los resultados obtenidos.

        Args:
            question:      Pregunta original del usuario.
            intent:        Análisis de intención.
            step_results:  Resultados de todos los pasos ejecutados.
            attempt:       Número de intento (para ajustar confianza).

        Returns:
            ReflectionResult con evaluación completa.
        """
        prompt = self._build_prompt(question, intent, step_results, attempt)

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = self.llm.invoke(messages)
            return self._parse(response.content, step_results)
        except Exception as e:
            return self._fallback(step_results, str(e))

    def _build_prompt(
        self,
        question: str,
        intent: IntentAnalysis,
        step_results: List[StepResult],
        attempt: int,
    ) -> str:
        # Formatear resultados de cada paso
        results_text = ""
        for sr in step_results:
            results_text += f"\n--- Paso {sr.step_number} ---\n"
            results_text += f"SQL ejecutado:\n{sr.sql}\n"
            if sr.success:
                results_text += f"Filas obtenidas: {sr.row_count}\n"
                if sr.rows:
                    # Mostrar primeras 3 filas como muestra
                    sample = sr.rows[:3]
                    results_text += f"Muestra de resultados: {sample}\n"
                if sr.anomalies:
                    results_text += f"ANOMALÍAS DETECTADAS: {'; '.join(sr.anomalies)}\n"
            else:
                results_text += f"ERROR: {sr.error_message}\n"

        # Penalizar por reintentos
        attempt_note = f"\nEsto es el intento #{attempt}." if attempt > 1 else ""

        return (
            f"PREGUNTA DEL USUARIO: {question}\n"
            f"DOMINIO: {intent.domain} | COMPLEJIDAD: {intent.complexity}\n"
            f"MÉTRICAS ESPERADAS: {', '.join(intent.metrics) or 'no especificadas'}\n"
            f"{attempt_note}\n\n"
            f"RESULTADOS OBTENIDOS:{results_text}\n\n"
            f"¿Este análisis responde correctamente la pregunta? Reflexiona:"
        )

    def _parse(self, text: str, step_results: List[StepResult]) -> ReflectionResult:
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                s = line.strip()
                if s.startswith(marker):
                    return s.split(":", 1)[1].strip() if ":" in s else default
            return default

        def get_list(marker: str) -> List[str]:
            raw = get(marker, "NONE")
            if raw.upper() == "NONE" or not raw:
                return []
            return [x.strip() for x in raw.split("|") if x.strip()]

        answered_raw = get("QUESTION_ANSWERED:", "PARTIAL").upper()
        question_answered = answered_raw == "YES"

        try:
            score = int(get("CONFIDENCE_SCORE:", "60"))
            score = max(0, min(100, score))
        except ValueError:
            score = 60

        # Penalizar si hay errores en los pasos
        failed_steps = [sr for sr in step_results if not sr.success]
        score -= len(failed_steps) * 15
        score = max(0, min(100, score))

        # Determinar nivel de confianza
        if score >= CONFIDENCE_THRESHOLDS["respond_normal"]:
            level = "normal"
        elif score >= CONFIDENCE_THRESHOLDS["respond_limited"]:
            level = "limited"
        elif score >= CONFIDENCE_THRESHOLDS["request_partial"]:
            level = "partial"
        else:
            level = "clarification"

        requires_retry_raw = get("REQUIRES_RETRY:", "NO").upper()
        requires_retry = requires_retry_raw == "YES" and score < 70

        return ReflectionResult(
            question_answered=question_answered,
            confidence_score=score,
            confidence_level=level,
            issues_found=get_list("ISSUES:"),
            corrections_needed=get_list("CORRECTIONS:"),
            reasoning=get("REASONING:", "Análisis reflexivo completado."),
            requires_retry=requires_retry,
            retry_hint=get("RETRY_HINT:", ""),
            business_rules_ok=get("BUSINESS_RULES_OK:", "YES").upper() == "YES",
            data_quality_ok=get("DATA_QUALITY_OK:", "YES").upper() == "YES",
        )

    @staticmethod
    def _fallback(step_results: List[StepResult], error: str) -> ReflectionResult:
        failed = sum(1 for sr in step_results if not sr.success)
        score = max(30, 70 - failed * 20)
        return ReflectionResult(
            question_answered=failed == 0,
            confidence_score=score,
            confidence_level="limited" if score >= 70 else "partial",
            issues_found=[f"Reflection LLM error: {error}"],
            corrections_needed=[],
            reasoning="Reflexión automática por error del LLM.",
            requires_retry=False,
            retry_hint="",
            business_rules_ok=True,
            data_quality_ok=failed == 0,
        )
