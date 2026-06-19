"""
agente/pipeline/response_formatter.py — Formateador de Respuestas Ejecutivas.

Convierte los resultados del análisis en una respuesta ejecutiva estructurada.

Formato de salida:
  ## Resumen Ejecutivo
  ## Hallazgos
  ## Evidencia (métricas y datos)
  ## Razonamiento
  ## Nivel de Confianza
  ## Limitaciones
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import (
    LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES,
    CONFIDENCE_THRESHOLDS,
)
from agente.agents.execution import StepResult
from agente.agents.reflection import ReflectionResult
from agente.agents.planner import AnalysisPlan
from agente.agents.intent_analyzer import IntentAnalysis


def _get_llm(temperature: float = 0.1, max_tokens: int = 1500):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=temperature, max_tokens=max_tokens,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class ExecutiveResponse:
    """Respuesta ejecutiva estructurada."""
    question: str
    executive_summary: str      # 2-3 frases respondiendo directamente
    findings: List[str]         # hallazgos principales en bullets
    evidence: str               # métricas y datos de soporte
    reasoning: str              # cómo se llegó a la conclusión
    confidence_score: int       # 0-100
    confidence_label: str       # Alta / Media / Limitada / Requiere aclaración
    limitations: List[str]      # supuestos y restricciones
    requires_clarification: bool
    clarification_questions: List[str]
    ambiguity_interpretations: List[str]  # si hay ambigüedad
    # Datos de debug (accesibles por la UI de Streamlit)
    step_results: Optional[List] = field(default=None)   # List[StepResult]
    trace_text: str = ""                                  # trazado ReAct

    def to_text(self) -> str:
        """Formatea la respuesta en texto Markdown."""
        lines = []

        # Alerta de ambigüedad
        if self.ambiguity_interpretations:
            lines.append("⚠️ **He identificado múltiples interpretaciones posibles:**")
            for i, interp in enumerate(self.ambiguity_interpretations, 1):
                lines.append(f"  {i}. {interp}")
            lines.append("")
            lines.append("Respondiendo con la interpretación más probable:")
            lines.append("")

        # Cuerpo principal
        lines.append("## Resumen Ejecutivo")
        lines.append(self.executive_summary)
        lines.append("")

        if self.findings:
            lines.append("## Hallazgos")
            for f in self.findings:
                lines.append(f"- {f}")
            lines.append("")

        if self.evidence:
            lines.append("## Evidencia")
            lines.append(self.evidence)
            lines.append("")

        lines.append("## Razonamiento")
        lines.append(self.reasoning)
        lines.append("")

        # Nivel de confianza con barra visual
        score = self.confidence_score
        filled = int(score / 10)
        bar = "█" * filled + "░" * (10 - filled)
        lines.append("## Nivel de Confianza")
        lines.append(f"**{self.confidence_label}** [{bar}] {score}/100")
        lines.append("")

        if self.limitations:
            lines.append("## Limitaciones")
            for lim in self.limitations:
                lines.append(f"- {lim}")
            lines.append("")

        if self.requires_clarification and self.clarification_questions:
            lines.append("## Aclaración Requerida")
            lines.append("Para mejorar la precisión de este análisis, necesito saber:")
            for q in self.clarification_questions:
                lines.append(f"- {q}")

        return "\n".join(lines)


SYSTEM_PROMPT = """Eres el analista senior de PayNova S.A. que presenta los resultados al equipo directivo.
Tu respuesta debe ser clara, ejecutiva y accionable. Usa el español de negocios.

Debes construir:
1. EXECUTIVE_SUMMARY: 2-3 frases que respondan directamente la pregunta con los datos encontrados.
   NO uses frases genéricas. Di el número, el porcentaje, el nombre del comercio, etc.
2. FINDINGS: 2-5 hallazgos específicos en formato de bullet. Cada uno debe tener un dato concreto.
3. REASONING: 2-3 párrafos explicando cómo se obtuvo la respuesta y qué significa para el negocio.
4. LIMITATIONS: restricciones o supuestos del análisis.

Responde en este FORMATO:
EXECUTIVE_SUMMARY: <resumen ejecutivo>
FINDING_1: <hallazgo 1 con dato concreto>
FINDING_2: <hallazgo 2>
[hasta FINDING_5]
REASONING: <razonamiento>
LIMITATION_1: <limitación 1>
LIMITATION_2: <limitación 2>"""


class ResponseFormatter:
    """
    Formatea los resultados del análisis en una respuesta ejecutiva.

    Usa el LLM para redactar la respuesta en lenguaje de negocio,
    integrando los datos obtenidos con el contexto empresarial.
    """

    def __init__(self):
        self.llm = _get_llm(temperature=0.1, max_tokens=1500)

    def format(
        self,
        question: str,
        intent: IntentAnalysis,
        plan: AnalysisPlan,
        step_results: List[StepResult],
        reflection: ReflectionResult,
    ) -> ExecutiveResponse:
        """
        Genera la respuesta ejecutiva final.

        Args:
            question:      Pregunta original del usuario.
            intent:        Análisis de intención.
            plan:          Plan de análisis ejecutado.
            step_results:  Resultados de todos los pasos.
            reflection:    Resultado de la reflexión.

        Returns:
            ExecutiveResponse con la respuesta formateada.
        """
        # Si requiere aclaración, generar respuesta de ambigüedad
        if intent.is_ambiguous and reflection.confidence_score < CONFIDENCE_THRESHOLDS["respond_limited"]:
            return self._ambiguity_response(question, intent, reflection)

        prompt = self._build_prompt(question, intent, plan, step_results, reflection)

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = self.llm.invoke(messages)
            return self._parse(response.content, question, intent, reflection)
        except Exception as e:
            return self._fallback_response(question, step_results, reflection, str(e))

    def _build_prompt(
        self,
        question: str,
        intent: IntentAnalysis,
        plan: AnalysisPlan,
        step_results: List[StepResult],
        reflection: ReflectionResult,
    ) -> str:
        # Compilar todos los datos obtenidos
        data_summary = self._compile_data(step_results)

        return (
            f"PREGUNTA: {question}\n\n"
            f"DOMINIO: {intent.domain} | COMPLEJIDAD: {intent.complexity}\n\n"
            f"PLAN EJECUTADO: {plan.overall_approach}\n\n"
            f"DATOS OBTENIDOS:\n{data_summary}\n\n"
            f"REFLEXIÓN DEL AGENTE: {reflection.reasoning}\n"
            f"Problemas detectados: {'; '.join(reflection.issues_found) or 'ninguno'}\n\n"
            f"Genera la respuesta ejecutiva para el directivo de PayNova:"
        )

    def _compile_data(self, step_results: List[StepResult]) -> str:
        """Compila los datos de todos los pasos en texto legible."""
        parts = []
        for sr in step_results:
            if sr.success and sr.rows:
                parts.append(f"Paso {sr.step_number} ({sr.row_count} filas):")
                # Mostrar hasta 5 filas con formato legible
                for i, row in enumerate(sr.rows[:5]):
                    row_str = " | ".join(f"{k}: {v}" for k, v in row.items() if v is not None)
                    parts.append(f"  [{i+1}] {row_str}")
                if sr.row_count > 5:
                    parts.append(f"  ... y {sr.row_count - 5} filas más")
            elif not sr.success:
                parts.append(f"Paso {sr.step_number}: ERROR - {sr.error_message}")
        return "\n".join(parts) if parts else "Sin datos obtenidos."

    def _parse(
        self,
        text: str,
        question: str,
        intent: IntentAnalysis,
        reflection: ReflectionResult,
    ) -> ExecutiveResponse:
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                s = line.strip()
                if s.startswith(marker):
                    return s.split(":", 1)[1].strip() if ":" in s else default
            return default

        # Hallazgos (FINDING_1 ... FINDING_5)
        findings = []
        for i in range(1, 6):
            f = get(f"FINDING_{i}:")
            if f:
                findings.append(f)

        # Limitaciones
        limitations = []
        for i in range(1, 4):
            lim = get(f"LIMITATION_{i}:")
            if lim:
                limitations.append(lim)

        # Añadir limitaciones del Reflection Agent
        for issue in reflection.issues_found[:2]:
            if issue and issue not in limitations:
                limitations.append(issue)

        confidence_label = {
            "normal":        "Alta",
            "limited":       "Media",
            "partial":       "Limitada",
            "clarification": "Requiere aclaración",
        }.get(reflection.confidence_level, "Media")

        return ExecutiveResponse(
            question=question,
            executive_summary=get("EXECUTIVE_SUMMARY:", "Análisis completado."),
            findings=findings,
            evidence=self._build_evidence_text(reflection),
            reasoning=get("REASONING:", reflection.reasoning),
            confidence_score=reflection.confidence_score,
            confidence_label=confidence_label,
            limitations=limitations,
            requires_clarification=reflection.confidence_level == "clarification",
            clarification_questions=reflection.corrections_needed[:3],
            ambiguity_interpretations=[intent.ambiguity_reason] if intent.is_ambiguous else [],
        )

    @staticmethod
    def _build_evidence_text(reflection: ReflectionResult) -> str:
        parts = []
        if not reflection.business_rules_ok:
            parts.append("⚠️ Se detectaron posibles violaciones a las reglas de negocio.")
        if not reflection.data_quality_ok:
            parts.append("⚠️ Calidad de datos cuestionable — revisar los resultados con cautela.")
        return "\n".join(parts) if parts else "Datos validados contra las reglas de negocio de PayNova."

    def _ambiguity_response(
        self,
        question: str,
        intent: IntentAnalysis,
        reflection: ReflectionResult,
    ) -> ExecutiveResponse:
        return ExecutiveResponse(
            question=question,
            executive_summary="He identificado múltiples interpretaciones posibles para esta pregunta.",
            findings=[],
            evidence="",
            reasoning=reflection.reasoning,
            confidence_score=reflection.confidence_score,
            confidence_label="Requiere aclaración",
            limitations=[],
            requires_clarification=True,
            clarification_questions=[
                "¿El análisis debe ser a nivel de usuarios o de comercios?",
                "¿Qué período de tiempo desea analizar?",
                f"Ambigüedad detectada: {intent.ambiguity_reason}",
            ],
            ambiguity_interpretations=[intent.ambiguity_reason] if intent.ambiguity_reason else [],
        )

    def _fallback_response(
        self,
        question: str,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        error: str,
    ) -> ExecutiveResponse:
        successful = [sr for sr in step_results if sr.success]
        summary = (
            f"Se obtuvieron datos de {len(successful)}/{len(step_results)} pasos del análisis. "
            f"El sistema procesó la pregunta pero no pudo generar una síntesis completa."
        )
        return ExecutiveResponse(
            question=question,
            executive_summary=summary,
            findings=[sr.summary for sr in successful[:3]],
            evidence="Ver logs del sistema para datos detallados.",
            reasoning=reflection.reasoning,
            confidence_score=reflection.confidence_score,
            confidence_label="Limitada",
            limitations=[f"Error en síntesis: {error[:100]}", "Respuesta generada en modo fallback."],
            requires_clarification=True,
            clarification_questions=["¿Puede reformular la pregunta con más detalle?"],
            ambiguity_interpretations=[],
        )
