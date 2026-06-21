"""
agente/agents/confidence_estimator.py — Mod 8: Composite Confidence Estimator.

Calcula un score de confianza COMPUESTO combinando seis fuentes de evidencia.
Reemplaza el score simple del ReflectionAgent (basado solo en pasos fallidos)
con una evaluacion multi-dimensional mas robusta.

Componentes y pesos:
  Retrieval KB        15%  — calidad y pertinencia del contexto recuperado
  Plan                15%  — coherencia y exito de la descomposicion en pasos
  SQL                 20%  — tasa de exito de los pasos SQL
  Business validation 20%  — coherencia con rangos y reglas de negocio
  Critic evaluation   20%  — LLM independiente (5 dimensiones ponderadas)
  Penalizacion iters  10%  — descuento proporcional a reintentos usados

Acciones segun score:
  90-100 -> respond   (responder con plena confianza)
  80-89  -> warn      (responder con observaciones menores)
  50-79  -> validate  (responder con advertencias, solicitar validacion)
  <50    -> clarify   (solicitar aclaracion al usuario, no responder)
"""

from dataclasses import dataclass, field
from typing import Dict, List

from agente.agents.execution import StepResult
from agente.agents.reflection import ReflectionResult
from agente.agents.critic import CriticResult
from agente.config import CONFIDENCE_THRESHOLDS


@dataclass
class ConfidenceEstimate:
    """Resultado del estimador de confianza compuesto."""
    score: int                           # 0-100 compuesto
    action: str                          # respond | warn | validate | clarify
    confidence_label: str                # Alta | Media | Limitada | Requiere aclaracion
    components: Dict[str, float]         # breakdown de cada componente


class ConfidenceEstimator:
    """
    Calcula confianza compuesta de seis componentes ponderados.

    Mod 8: Se ejecuta entre el critic_agent y format_response.
    Provee el score final y la accion recomendada para el ResponseFormatter.
    """

    def estimate(
        self,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        critic: CriticResult,
        business_flags: List[str],
        react_iterations: int,
        critic_iterations: int,
        kb_was_retrieved: bool = True,
    ) -> ConfidenceEstimate:
        """
        Calcula el score de confianza compuesto.

        Args:
            step_results:      Resultados de todos los pasos ejecutados.
            reflection:        Resultado de la primera capa de reflexion.
            critic:            Resultado del CriticAgent.
            business_flags:    Flags de validacion empresarial acumulados.
            react_iterations:  Iteraciones ReAct usadas (>1 = hubo reintentos).
            critic_iterations: Iteraciones del critic (>1 = critic reintento).
            kb_was_retrieved:  Si se recupero contexto relevante de la KB.

        Returns:
            ConfidenceEstimate con score, accion y breakdown.
        """
        failed   = sum(1 for r in step_results if not r.success)
        total    = max(1, len(step_results))
        success_rate = (total - failed) / total

        # ── Componente 1: Retrieval KB (15%) ─────────────────────────────────
        retrieval_score = 90 if kb_was_retrieved else 55

        # ── Componente 2: Plan (15%) ──────────────────────────────────────────
        # Proxy: porcentaje de pasos exitosos
        plan_score = int(55 + 45 * success_rate)   # 55-100

        # ── Componente 3: SQL (20%) ───────────────────────────────────────────
        sql_score = max(15, 100 - failed * 25)

        # ── Componente 4: Business validation (20%) ───────────────────────────
        biz_score = max(35, 100 - len(business_flags) * 12)

        # ── Componente 5: Critic (20%) ────────────────────────────────────────
        # Promedio ponderado de las 5 dimensiones del critic
        critic_raw = int(
            critic.exactness        * 0.30 +
            critic.consistency      * 0.25 +
            critic.analytic_quality * 0.20 +
            critic.executive_quality * 0.25
        )
        # Penalizacion por riesgo de alucinacion
        hal_penalty = {"high": 30, "medium": 15, "low": 0}.get(critic.hallucination_risk, 0)
        critic_score = max(10, critic_raw - hal_penalty)

        # ── Componente 6: Penalizacion por iteraciones (10%) ─────────────────
        # Cuantos mas reintentos, menor confianza en la respuesta final
        react_pen  = min(20, (react_iterations - 1) * 5)
        critic_pen = min(10, (critic_iterations - 1) * 5)
        iter_score = max(60, 100 - react_pen - critic_pen)

        # ── Score compuesto (ponderado) ───────────────────────────────────────
        composite = (
            retrieval_score * 0.15 +
            plan_score      * 0.15 +
            sql_score       * 0.20 +
            biz_score       * 0.20 +
            critic_score    * 0.20 +
            iter_score      * 0.10
        )
        score = int(max(0, min(100, composite)))

        # ── Accion y label ────────────────────────────────────────────────────
        if score >= CONFIDENCE_THRESHOLDS["respond_normal"]:
            action = "respond"
            label  = "Alta"
        elif score >= CONFIDENCE_THRESHOLDS["respond_limited"]:
            action = "warn"
            label  = "Media"
        elif score >= CONFIDENCE_THRESHOLDS["request_partial"]:
            action = "validate"
            label  = "Limitada"
        else:
            action = "clarify"
            label  = "Requiere aclaracion"

        components = {
            "retrieval":    float(retrieval_score),
            "plan":         float(plan_score),
            "sql":          float(sql_score),
            "business":     float(biz_score),
            "critic":       float(critic_score),
            "iter_penalty": float(react_pen + critic_pen),
        }

        return ConfidenceEstimate(
            score=score,
            action=action,
            confidence_label=label,
            components=components,
        )
