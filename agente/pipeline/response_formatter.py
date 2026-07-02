"""
agente/pipeline/response_formatter.py — Formateador de Respuestas Ejecutivas (Mod 9).

Convierte los resultados del analisis en una respuesta ejecutiva estructurada
para CEO/CFO/COO con 7 secciones segun el formato evolucionado:

  1. Resumen Ejecutivo
  2. Hallazgos
  3. Evidencia (metricas y datos)
  4. Razonamiento
  5. Riesgos Identificados          [NUEVO Mod 9]
  6. Recomendaciones Accionables    [NUEVO Mod 9]
  7. Nivel de Confianza + Limitaciones
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


def _get_llm(temperature: float = 0.1, max_tokens: int = 1800):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=temperature, max_tokens=max_tokens,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class ExecutiveResponse:
    """Respuesta ejecutiva estructurada (evolucionada con Mod 9)."""
    question: str
    executive_summary: str              # 2-3 frases respondiendo directamente
    findings: List[str]                 # hallazgos principales en bullets
    evidence: str                       # metricas y datos de soporte
    reasoning: str                      # como se llego a la conclusion
    confidence_score: int               # 0-100
    confidence_label: str               # Alta / Media / Limitada / Requiere aclaracion
    limitations: List[str]              # supuestos y restricciones
    requires_clarification: bool
    clarification_questions: List[str]
    ambiguity_interpretations: List[str]
    # ── Campos nuevos Mod 9 ──────────────────────────────────────────────────
    risks: List[str] = field(default_factory=list)                  # riesgos identificados
    recommendations: List[str] = field(default_factory=list)        # recomendaciones accionables
    confidence_components: Optional[Dict[str, float]] = None        # breakdown 6 componentes
    critic_verdict: str = "sufficient"                              # veredicto del critic
    kb_was_sufficient: bool = False                                 # respondio directamente de KB
    dashboard_reference: str = ""                                   # Mod 10: dashboard(s) relacionados
    # ── Datos de debug ────────────────────────────────────────────────────────
    step_results: Optional[List] = field(default=None)             # List[StepResult]
    trace_text: str = ""                                            # trazado ReAct

    def to_text(self) -> str:
        """Formatea la respuesta en texto Markdown (7 secciones)."""
        lines = []

        # Banner KB-directo
        if self.kb_was_sufficient:
            lines.append("ℹ️ **Respuesta directa desde documentacion empresarial** "
                         "(sin consulta a base de datos)")
            lines.append("")

        # Banner de dashboard relacionado [Mod 10]
        if self.dashboard_reference:
            lines.append(f"📊 **Datos también visualizados en el dashboard:** {self.dashboard_reference}")
            lines.append("")

        # Alerta de ambiguedad
        if self.ambiguity_interpretations:
            lines.append("⚠️ **Multiples interpretaciones posibles:**")
            for i, interp in enumerate(self.ambiguity_interpretations, 1):
                lines.append(f"  {i}. {interp}")
            lines.append("")
            lines.append("Respondiendo con la interpretacion mas probable:")
            lines.append("")

        # 1. Resumen Ejecutivo
        lines.append("## Resumen Ejecutivo")
        lines.append(self.executive_summary)
        lines.append("")

        # 2. Hallazgos
        if self.findings:
            lines.append("## Hallazgos")
            for f in self.findings:
                lines.append(f"- {f}")
            lines.append("")

        # 3. Evidencia
        if self.evidence:
            lines.append("## Evidencia")
            lines.append(self.evidence)
            lines.append("")

        # 4. Razonamiento
        lines.append("## Razonamiento")
        lines.append(self.reasoning)
        lines.append("")

        # 5. Riesgos Identificados [Mod 9]
        if self.risks:
            lines.append("## Riesgos Identificados")
            for r in self.risks:
                lines.append(f"- {r}")
            lines.append("")

        # 6. Recomendaciones Accionables [Mod 9]
        if self.recommendations:
            lines.append("## Recomendaciones")
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        # 7. Nivel de Confianza
        score  = self.confidence_score
        filled = int(score / 10)
        bar    = "█" * filled + "░" * (10 - filled)
        lines.append("## Nivel de Confianza")
        lines.append(f"**{self.confidence_label}** [{bar}] {score}/100")

        if self.confidence_components:
            comps = self.confidence_components
            lines.append("")
            lines.append("Componentes:")
            labels = {
                "retrieval": "Recuperacion KB",
                "plan": "Plan",
                "sql": "SQL",
                "business": "Validacion negocio",
                "critic": "Critic agent",
                "iter_penalty": "Penalizacion reintentos",
            }
            for key, label in labels.items():
                val = comps.get(key, 0)
                lines.append(f"  - {label}: {int(val)}")
        lines.append("")

        if self.limitations:
            lines.append("## Limitaciones")
            for lim in self.limitations:
                lines.append(f"- {lim}")
            lines.append("")

        if self.requires_clarification and self.clarification_questions:
            lines.append("## Aclaracion Requerida")
            lines.append("Para mejorar la precision de este analisis:")
            for q in self.clarification_questions:
                lines.append(f"- {q}")

        return "\n".join(lines)


SYSTEM_PROMPT = """Eres el analista senior de PayNova S.A. que presenta los resultados al equipo directivo.
Tu respuesta debe ser clara, ejecutiva y accionable. Usa el espanol de negocios.

Construye UNA RESPUESTA CON 7 SECCIONES:

1. EXECUTIVE_SUMMARY: 2-3 frases respondiendo DIRECTAMENTE la pregunta con numeros concretos.
   NUNCA uses frases genericas. Di el valor, el porcentaje, el comercio, la fecha.

2. FINDINGS: 2-5 hallazgos especificos con datos concretos (FINDING_1 a FINDING_5).

3. REASONING: 2-3 parrafos explicando como se obtuvo la respuesta y que significa para el negocio.

4. RISK_1/RISK_2/RISK_3: Riesgos reales identificados en los datos (OMITIR si no hay riesgos).
   Cada riesgo debe ser especifico y accionable (ej: "Tasa de fraude de 3.2% supera el objetivo de 0.5%").

5. RECOMMENDATION_1/RECOMMENDATION_2/RECOMMENDATION_3: Acciones concretas derivadas del analisis.
   Cada recomendacion debe ser especifica: quien, que, cuando (ej: "Revisar 23 comercios con MDR < 1.5%").

6. LIMITATION_1/LIMITATION_2: restricciones o supuestos del analisis.

Formato EXACTO:
EXECUTIVE_SUMMARY: <resumen>
FINDING_1: <hallazgo 1>
FINDING_2: <hallazgo 2>
[hasta FINDING_5]
REASONING: <razonamiento 2-3 parrafos>
RISK_1: <riesgo 1 o NONE>
RISK_2: <riesgo 2 o NONE>
RISK_3: <riesgo 3 o NONE>
RECOMMENDATION_1: <accion 1 o NONE>
RECOMMENDATION_2: <accion 2 o NONE>
RECOMMENDATION_3: <accion 3 o NONE>
LIMITATION_1: <limitacion 1>
LIMITATION_2: <limitacion 2 o NONE>"""


class ResponseFormatter:
    """
    Formatea los resultados del analisis en una respuesta ejecutiva de 7 secciones.

    Mod 9: Incorpora riesgos, recomendaciones, breakdown de confianza,
    veredicto del critic y banner KB-directo.
    """

    def __init__(self):
        self.llm = _get_llm(temperature=0.1, max_tokens=1800)

    def format(
        self,
        question: str,
        intent: IntentAnalysis,
        plan: AnalysisPlan,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        business_flags: Optional[List[str]] = None,
        confidence_estimate=None,       # ConfidenceEstimate | None
        critic=None,                    # CriticResult | None
        kb_was_sufficient: bool = False,
        dashboard_reference: str = "",
    ) -> "ExecutiveResponse":
        """
        Genera la respuesta ejecutiva final de 7 secciones.

        Args:
            question:            Pregunta original del usuario.
            intent:              Analisis de intencion.
            plan:                Plan de analisis ejecutado.
            step_results:        Resultados de todos los pasos.
            reflection:          Resultado de la reflexion.
            business_flags:      Flags de validacion empresarial (Mod 5).
            confidence_estimate: ConfidenceEstimate compuesto (Mod 8).
            critic:              CriticResult del agente critico (Mod 6).
            kb_was_sufficient:   Si la KB fue suficiente sin SQL (Mod 1).
            dashboard_reference: Dashboard(s) Power BI relacionados, si aplica (Mod 10).

        Returns:
            ExecutiveResponse con la respuesta formateada de 7 secciones.
        """
        business_flags = business_flags or []

        # Obtener score y label de confianza
        if confidence_estimate is not None:
            conf_score = confidence_estimate.score
            conf_label = confidence_estimate.confidence_label
            conf_components = confidence_estimate.components
            conf_action     = confidence_estimate.action
        else:
            conf_score = reflection.confidence_score
            conf_label = {
                "normal":        "Alta",
                "limited":       "Media",
                "partial":       "Limitada",
                "clarification": "Requiere aclaracion",
            }.get(reflection.confidence_level, "Media")
            conf_components = None
            conf_action     = "respond" if conf_score >= 70 else "validate"

        critic_verdict = critic.verdict if critic is not None else "sufficient"

        # Aclaracion requerida
        if (intent.is_ambiguous and conf_score < CONFIDENCE_THRESHOLDS["respond_limited"]
                or conf_action == "clarify"):
            return self._ambiguity_response(
                question, intent, reflection, conf_score, conf_label,
                conf_components, critic_verdict, kb_was_sufficient, dashboard_reference,
            )

        prompt = self._build_prompt(
            question, intent, plan, step_results, reflection,
            business_flags, critic,
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            return self._parse(
                response.content, question, intent, reflection,
                conf_score, conf_label, conf_components,
                business_flags, critic_verdict, kb_was_sufficient, dashboard_reference,
            )
        except Exception as e:
            return self._fallback_response(
                question, step_results, reflection,
                conf_score, conf_label, conf_components,
                critic_verdict, kb_was_sufficient, str(e), dashboard_reference,
            )

    def _build_prompt(
        self,
        question: str,
        intent: IntentAnalysis,
        plan: AnalysisPlan,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        business_flags: List[str],
        critic,
    ) -> str:
        data_summary   = self._compile_data(step_results)
        biz_flags_text = (
            "\n".join(f"  - {f}" for f in business_flags)
            if business_flags else "  Ninguna anomalia detectada."
        )
        critic_text = ""
        if critic is not None:
            critic_text = (
                f"\n\nEVALUACION DEL CRITIC AGENT:\n"
                f"  Exactitud: {critic.exactness}/100 | "
                f"  Consistencia: {critic.consistency}/100 | "
                f"  Calidad ejecutiva: {critic.executive_quality}/100\n"
                f"  Riesgo de alucinacion: {critic.hallucination_risk}\n"
                f"  Razonamiento: {critic.reasoning}"
            )

        return (
            f"PREGUNTA: {question}\n\n"
            f"DOMINIO: {intent.domain} | COMPLEJIDAD: {intent.complexity}\n\n"
            f"PLAN EJECUTADO: {plan.overall_approach}\n\n"
            f"DATOS OBTENIDOS:\n{data_summary}\n\n"
            f"FLAGS DE VALIDACION EMPRESARIAL:\n{biz_flags_text}"
            f"{critic_text}\n\n"
            f"REFLEXION DEL AGENTE: {reflection.reasoning}\n"
            f"Problemas detectados: {'; '.join(reflection.issues_found) or 'ninguno'}\n\n"
            f"Genera la respuesta ejecutiva de 7 secciones para el equipo directivo de PayNova:"
        )

    def _compile_data(self, step_results: List[StepResult]) -> str:
        parts = []
        for sr in step_results:
            if sr.success and sr.rows:
                parts.append(f"Paso {sr.step_number} ({sr.row_count} filas):")
                for i, row in enumerate(sr.rows[:5]):
                    row_str = " | ".join(f"{k}: {v}" for k, v in row.items() if v is not None)
                    parts.append(f"  [{i+1}] {row_str}")
                if sr.row_count > 5:
                    parts.append(f"  ... y {sr.row_count - 5} filas mas")
            elif not sr.success:
                parts.append(f"Paso {sr.step_number}: ERROR - {sr.error_message}")
        return "\n".join(parts) if parts else "Sin datos obtenidos."

    def _parse(
        self,
        text: str,
        question: str,
        intent: IntentAnalysis,
        reflection: ReflectionResult,
        conf_score: int,
        conf_label: str,
        conf_components: Optional[Dict[str, float]],
        business_flags: List[str],
        critic_verdict: str,
        kb_was_sufficient: bool,
        dashboard_reference: str = "",
    ) -> "ExecutiveResponse":
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                s = line.strip()
                if s.startswith(marker):
                    return s.split(":", 1)[1].strip() if ":" in s else default
            return default

        # Hallazgos
        findings = []
        for i in range(1, 6):
            f = get(f"FINDING_{i}:")
            if f:
                findings.append(f)

        # Limitaciones
        limitations = []
        for i in range(1, 4):
            lim = get(f"LIMITATION_{i}:")
            if lim and lim.upper() != "NONE":
                limitations.append(lim)
        for issue in reflection.issues_found[:2]:
            if issue and issue not in limitations:
                limitations.append(issue)

        # Riesgos [Mod 9]
        risks = []
        for i in range(1, 4):
            r = get(f"RISK_{i}:")
            if r and r.upper() != "NONE":
                risks.append(r)
        # Agregar flags empresariales como riesgos adicionales
        for flag in business_flags[:2]:
            if flag and flag not in risks:
                risks.append(flag)

        # Recomendaciones [Mod 9]
        recommendations = []
        for i in range(1, 4):
            rec = get(f"RECOMMENDATION_{i}:")
            if rec and rec.upper() != "NONE":
                recommendations.append(rec)

        return ExecutiveResponse(
            question=question,
            executive_summary=get("EXECUTIVE_SUMMARY:", "Analisis completado."),
            findings=findings,
            evidence=self._build_evidence_text(reflection, business_flags),
            reasoning=get("REASONING:", reflection.reasoning),
            confidence_score=conf_score,
            confidence_label=conf_label,
            limitations=limitations,
            requires_clarification=(conf_score < CONFIDENCE_THRESHOLDS["request_partial"]),
            clarification_questions=reflection.corrections_needed[:3],
            ambiguity_interpretations=[intent.ambiguity_reason] if intent.is_ambiguous else [],
            risks=risks,
            recommendations=recommendations,
            confidence_components=conf_components,
            critic_verdict=critic_verdict,
            kb_was_sufficient=kb_was_sufficient,
            dashboard_reference=dashboard_reference,
        )

    @staticmethod
    def _build_evidence_text(reflection: ReflectionResult, business_flags: List[str]) -> str:
        parts = []
        if not reflection.business_rules_ok:
            parts.append("Posibles violaciones a las reglas de negocio detectadas.")
        if not reflection.data_quality_ok:
            parts.append("Calidad de datos cuestionable — revisar con cautela.")
        for flag in business_flags[:3]:
            parts.append(f"Flag: {flag}")
        return "\n".join(parts) if parts else "Datos validados contra las reglas de negocio de PayNova."

    def _ambiguity_response(
        self,
        question: str,
        intent: IntentAnalysis,
        reflection: ReflectionResult,
        conf_score: int,
        conf_label: str,
        conf_components: Optional[Dict[str, float]],
        critic_verdict: str,
        kb_was_sufficient: bool,
        dashboard_reference: str = "",
    ) -> "ExecutiveResponse":
        return ExecutiveResponse(
            question=question,
            executive_summary="Se han identificado multiples interpretaciones posibles para esta pregunta.",
            findings=[],
            evidence="",
            reasoning=reflection.reasoning,
            confidence_score=conf_score,
            confidence_label="Requiere aclaracion",
            limitations=[],
            requires_clarification=True,
            clarification_questions=[
                "El analisis debe ser a nivel de usuarios o de comercios?",
                "Que periodo de tiempo desea analizar?",
                f"Ambiguedad detectada: {intent.ambiguity_reason}",
            ],
            ambiguity_interpretations=[intent.ambiguity_reason] if intent.ambiguity_reason else [],
            risks=[],
            recommendations=[],
            confidence_components=conf_components,
            critic_verdict=critic_verdict,
            kb_was_sufficient=kb_was_sufficient,
            dashboard_reference=dashboard_reference,
        )

    def _fallback_response(
        self,
        question: str,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        conf_score: int,
        conf_label: str,
        conf_components: Optional[Dict[str, float]],
        critic_verdict: str,
        kb_was_sufficient: bool,
        error: str,
        dashboard_reference: str = "",
    ) -> "ExecutiveResponse":
        successful = [sr for sr in step_results if sr.success]
        summary = (
            f"Se obtuvieron datos de {len(successful)}/{len(step_results)} pasos del analisis. "
            f"El sistema proceso la pregunta pero no pudo generar una sintesis completa."
        )
        return ExecutiveResponse(
            question=question,
            executive_summary=summary,
            findings=[sr.summary for sr in successful[:3]],
            evidence="Ver logs del sistema para datos detallados.",
            reasoning=reflection.reasoning,
            confidence_score=conf_score,
            confidence_label="Limitada",
            limitations=[
                f"Error en sintesis: {error[:100]}",
                "Respuesta generada en modo fallback.",
            ],
            requires_clarification=True,
            clarification_questions=["Puede reformular la pregunta con mas detalle?"],
            ambiguity_interpretations=[],
            risks=[],
            recommendations=[],
            confidence_components=conf_components,
            critic_verdict=critic_verdict,
            kb_was_sufficient=kb_was_sufficient,
            dashboard_reference=dashboard_reference,
        )
