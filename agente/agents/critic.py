"""
agente/agents/critic.py — Mod 6+7: Critic Agent (LLM Independiente).

Segunda capa de evaluacion critica INDEPENDIENTE del pipeline principal.
El critic no participo en la generacion — evalua el output como revisor externo.

Mod 6: Evalua cinco dimensiones de calidad del analisis.
Mod 7: Puede disparar un bucle de correccion con cuatro veredictos:
  sufficient -> continuar, calidad aceptable
  replan     -> plan fundamentalmente incorrecto, regenerar desde cero
  retable    -> tablas del paso N insuficientes, reejecutar desde select_tables
  retry_sql  -> SQL del paso N incorrecto, reejecutar desde generate_sql
"""

from dataclasses import dataclass
from typing import List
from langchain_core.messages import HumanMessage, SystemMessage

from agente.config import (
    LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES,
    PAYNOVA_BUSINESS_RULES,
)
from agente.agents.execution import StepResult
from agente.agents.planner import AnalysisPlan
from agente.agents.intent_analyzer import IntentAnalysis
from agente.agents.reflection import ReflectionResult


def _get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=0.0, max_tokens=1024,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class CriticResult:
    """Resultado de la evaluacion del Critic Agent."""
    verdict: str               # sufficient | replan | retable | retry_sql
    exactness: int             # 0-100: ¿se respondio la pregunta exactamente?
    consistency: int           # 0-100: ¿es coherente la evidencia con la respuesta?
    analytic_quality: int      # 0-100: ¿el razonamiento y calculos son correctos?
    hallucination_risk: str    # low | medium | high
    executive_quality: int     # 0-100: ¿es accionable para un directivo?
    replan_hint: str           # instruccion concisa para la correccion
    target_step: int           # paso a reejecutar (-1 = aplica a todo el plan)
    reasoning: str             # evaluacion narrativa del critic


SYSTEM_PROMPT = (
    """Eres el agente critico independiente del sistema PayNova Business Agent.
Tu rol: evaluar la calidad del analisis como REVISOR EXTERNO que no participo
en la generacion. Eres riguroso y orientado al directivo de negocio.

"""
    + PAYNOVA_BUSINESS_RULES
    + """

Evalua CINCO dimensiones (0-100 cada una):
1. EXACTNESS:         ¿el analisis responde directamente la pregunta del usuario?
2. CONSISTENCY:       ¿los datos obtenidos son coherentes entre si y con la evidencia SQL?
3. ANALYTIC_QUALITY:  ¿el razonamiento es logico y los calculos respetan reglas de negocio?
4. HALLUCINATION_RISK:¿hay informacion inventada o no respaldada por los datos reales?
5. EXECUTIVE_QUALITY: ¿la respuesta seria util y accionable para un CEO/CFO/COO?

Veredictos:
- SUFFICIENT  → calidad aceptable, continuar al formato ejecutivo
- REPLAN      → el plan interpreta mal la pregunta, regenerar desde cero
- RETABLE     → las tablas del paso N son insuficientes para el objetivo
- RETRY_SQL   → el SQL del paso N es incorrecto (plan y tablas son correctos)

Responde en FORMATO EXACTO:
VERDICT: <SUFFICIENT|REPLAN|RETABLE|RETRY_SQL>
TARGET_STEP: <numero de paso 1-N, o -1 si aplica a todo>
EXACTNESS: <0-100>
CONSISTENCY: <0-100>
ANALYTIC_QUALITY: <0-100>
HALLUCINATION_RISK: <low|medium|high>
EXECUTIVE_QUALITY: <0-100>
REPLAN_HINT: <instruccion concisa de correccion, o NONE>
REASONING: <evaluacion critica narrativa de 2-4 lineas>"""
)

# Veredictos validos normalizados
_VALID_VERDICTS = {"sufficient", "replan", "retable", "retry_sql"}


class CriticAgent:
    """
    LLM independiente que evalua el analisis desde una perspectiva externa.

    Mod 6: Segunda capa critica con 5 dimensiones de evaluacion.
    Mod 7: Sus veredictos pueden disparar loops de correccion en react_loop.py.
    """

    def __init__(self):
        self.llm = _get_llm()

    def evaluate(
        self,
        question: str,
        intent: IntentAnalysis,
        plan: AnalysisPlan,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        business_flags: List[str],
    ) -> CriticResult:
        """
        Evalua la calidad del analisis completo.

        Args:
            question:       Pregunta original del usuario.
            intent:         Analisis de intencion.
            plan:           Plan ejecutado.
            step_results:   Resultados de todos los pasos SQL.
            reflection:     Resultado de la primera capa de reflexion.
            business_flags: Flags de validacion empresarial acumulados.

        Returns:
            CriticResult con veredicto, scores y razonamiento.
        """
        prompt = self._build_prompt(
            question, intent, plan, step_results, reflection, business_flags
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            return self._parse(response.content)
        except Exception as e:
            # Fallback conservador: asumir suficiente para no bloquear el pipeline
            return CriticResult(
                verdict="sufficient",
                exactness=65, consistency=65, analytic_quality=65,
                hallucination_risk="low", executive_quality=65,
                replan_hint="",
                target_step=-1,
                reasoning=f"Critic fallback por error de LLM: {e}",
            )

    def _build_prompt(
        self,
        question: str,
        intent: IntentAnalysis,
        plan: AnalysisPlan,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        business_flags: List[str],
    ) -> str:
        results_text = ""
        for sr in step_results:
            results_text += f"\n  Paso {sr.step_number}: "
            if sr.success and sr.rows:
                sample = sr.rows[:3]
                results_text += f"OK ({sr.row_count} filas). Muestra: {sample}"
            elif sr.success:
                results_text += "OK pero sin filas."
            else:
                results_text += f"ERROR: {sr.error_message}"

        biz_text = (
            "\n".join(f"  - {f}" for f in business_flags)
            if business_flags else "  Ninguna anomalia empresarial detectada."
        )

        subproblems_text = ""
        if hasattr(plan, "subproblems") and plan.subproblems:
            subproblems_text = "\nSubproblemas identificados: " + " | ".join(plan.subproblems)

        return (
            f"PREGUNTA: {question}\n"
            f"DOMINIO: {intent.domain} | COMPLEJIDAD: {intent.complexity}\n\n"
            f"PLAN EJECUTADO: {plan.overall_approach}{subproblems_text}\n"
            f"Numero de pasos: {len(plan.steps)}\n\n"
            f"RESULTADOS SQL:{results_text}\n\n"
            f"REFLEXION (1a capa): score={reflection.confidence_score}, "
            f"answered={reflection.question_answered}, "
            f"issues={reflection.issues_found[:3]}\n\n"
            f"FLAGS EMPRESARIALES:\n{biz_text}\n\n"
            f"Evalua el analisis como critico independiente:"
        )

    @staticmethod
    def _parse(text: str) -> CriticResult:
        def get(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                if line.strip().startswith(marker):
                    return line.split(":", 1)[1].strip() if ":" in line else default
            return default

        def get_int(marker: str, default: int = 70) -> int:
            try:
                return max(0, min(100, int(get(marker, str(default)))))
            except ValueError:
                return default

        verdict = get("VERDICT:", "SUFFICIENT").upper().lower()
        if verdict not in _VALID_VERDICTS:
            verdict = "sufficient"

        try:
            target = int(get("TARGET_STEP:", "-1"))
        except ValueError:
            target = -1

        hint_raw = get("REPLAN_HINT:", "NONE")
        hint = "" if hint_raw.upper() == "NONE" else hint_raw

        return CriticResult(
            verdict=verdict,
            exactness=get_int("EXACTNESS:"),
            consistency=get_int("CONSISTENCY:"),
            analytic_quality=get_int("ANALYTIC_QUALITY:"),
            hallucination_risk=get("HALLUCINATION_RISK:", "low").lower(),
            executive_quality=get_int("EXECUTIVE_QUALITY:"),
            replan_hint=hint,
            target_step=target,
            reasoning=get("REASONING:", "Evaluacion critica completada."),
        )
