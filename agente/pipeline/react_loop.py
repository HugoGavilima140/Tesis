"""
agente/pipeline/react_loop.py — Orquestador ReAct Evolucionado del Business Reasoning Agent.

Integra las 10 modificaciones sobre la arquitectura ReAct + Multi-Hop original:

  Mod 1:  Business Knowledge Validation   — KB suficiente? Skip SQL.
  Mod 2:  Memory Retrieval previo         — recuperar errores/exitos ANTES de la KB.
  Mod 3:  Subproblemas explicitos         — MultiHopPlanner descompone en subproblemas.
  Mod 4:  Table Validation                — valida cobertura antes de generar SQL.
  Mod 5:  Business Validation             — valida resultados contra reglas de negocio.
  Mod 6:  Critic Agent                    — segunda capa de evaluacion independiente.
  Mod 7:  Bucle de correccion del critic  — puede disparar replan/retable/retry_sql.
  Mod 8:  Confidence Estimator compuesto  — score multi-dimensional antes del formato.
  Mod 9:  Formato ejecutivo mejorado      — 7 secciones para CEO/CFO/COO.
  Mod 10: Dashboard Context Validation    — ¿la pregunta corresponde a algun dashboard
          Power BI? Si es asi, reformula la pregunta en terminos del modelo de datos
          real (medidas DAX, tablas SQL) y ese contexto guia planificacion + SQL.

Flujo evolucionado:
  Pregunta
    ↓ Cache check
    ↓ THINK: Analisis de intencion
    ↓ ACT: Recuperacion de memoria historica     [Mod 2]
    ↓ ACT: Recuperacion de conocimiento KB
    ↓ THINK: ¿La pregunta corresponde a un dashboard Power BI? [Mod 10]
      └── Si: reformular en terminos de datos + medidas/tablas reales → enriquecer contexto
    ↓ OBSERVE+THINK: Validacion KB suficiente?   [Mod 1]
      ├── Si: Synthesis directo → saltar SQL pipeline
      └── No:
            ↓ THINK+ACT: Planificacion multi-hop [Mod 3]
            ↓ Para cada paso:
              ↓ THINK: Seleccionar tablas
              ↓ THINK+VALIDATE: Validar tablas    [Mod 4]
              ↓ THINK: Generar SQL
              ↓ ACT: Ejecutar SQL
              ↓ OBSERVE+VALIDATE: Validar negocio [Mod 5]
            ↓ THINK: Reflexion primera capa
            ↓ retry si score < 70
    ↓ THINK: Critic Agent (LLM independiente)    [Mod 6]
    ↓ retry segun veredicto                      [Mod 7]
    ↓ COMPUTE: Confianza compuesta               [Mod 8]
    ↓ FORMAT: Respuesta ejecutiva 7 secciones    [Mod 9]
    ↓ MemoryAgent → persistir aprendizaje
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import time

from agente.agents.intent_analyzer import IntentAnalyzerAgent, IntentAnalysis
from agente.agents.planner import MultiHopPlanner, AnalysisPlan, PlanStep
from agente.agents.table_retrieval import TableRetrievalAgent, TableSelection
from agente.agents.sql_reasoning import SQLReasoningAgent, GeneratedSQL
from agente.agents.execution import ExecutionAgent, StepResult
from agente.agents.reflection import ReflectionAgent, ReflectionResult
from agente.agents.memory import MemoryAgent
from agente.knowledge.retriever import BusinessKnowledgeRetriever
from agente.pipeline.response_formatter import ResponseFormatter, ExecutiveResponse

# Agentes nuevos (modificaciones)
from agente.agents.business_knowledge_validator import BusinessKnowledgeValidator, KBValidationResult
from agente.agents.table_validator import TableValidator
from agente.agents.business_validator import BusinessValidator
from agente.agents.critic import CriticAgent, CriticResult
from agente.agents.confidence_estimator import ConfidenceEstimator, ConfidenceEstimate
from agente.agents.dashboard_validator import DashboardContextAgent, DashboardContextResult

from agente.config import (
    MAX_REACT_ITERATIONS, MAX_RETRIES_SQL, MAX_TABLE_RETRIES, MAX_CRITIC_ITERS,
    CONFIDENCE_THRESHOLDS,
)


@dataclass
class ReActTrace:
    """Trazado completo del ciclo ReAct para auditoría y debugging."""
    question: str
    iterations: List[dict] = field(default_factory=list)
    total_time_s: float = 0.0
    final_confidence: int = 0
    retry_count: int = 0

    def add_step(self, phase: str, thought: str, action: str, observation: str) -> None:
        self.iterations.append({
            "phase": phase,
            "thought": thought,
            "action": action,
            "observation": observation[:300],
        })

    def to_text(self) -> str:
        lines = [f"=== ReAct Trace: {self.question[:80]} ==="]
        for i, step in enumerate(self.iterations, 1):
            lines.append(f"\n[{i}] {step['phase'].upper()}")
            lines.append(f"  THOUGHT: {step['thought']}")
            lines.append(f"  ACTION:  {step['action']}")
            lines.append(f"  OBSERVE: {step['observation']}")
        lines.append(
            f"\nConfianza final: {self.final_confidence}/100 | "
            f"Reintentos: {self.retry_count} | "
            f"Tiempo: {self.total_time_s:.1f}s"
        )
        return "\n".join(lines)


class BusinessReasoningAgent:
    """
    Agente de Razonamiento Empresarial evolucionado con arquitectura
    ReAct + Multi-Hop + 9 Modificaciones del estado del arte.
    """

    def __init__(self, force_rebuild_kb: bool = False):
        print("[ReAct] Inicializando Business Reasoning Agent (Arquitectura Evolucionada)...")

        # KB
        self.kb_retriever = BusinessKnowledgeRetriever()
        self.kb_retriever.initialize(force_rebuild=force_rebuild_kb)

        # Agentes originales
        self.intent_agent    = IntentAnalyzerAgent()
        self.planner         = MultiHopPlanner()
        self.table_retrieval = TableRetrievalAgent()
        self.sql_reasoning   = SQLReasoningAgent()
        self.execution       = ExecutionAgent()
        self.reflection      = ReflectionAgent()
        self.memory          = MemoryAgent()
        self.formatter       = ResponseFormatter()

        # Agentes nuevos (modificaciones)
        self.kb_validator         = BusinessKnowledgeValidator()   # Mod 1
        self.table_validator      = TableValidator()               # Mod 4
        self.business_validator   = BusinessValidator()            # Mod 5
        self.critic               = CriticAgent()                  # Mod 6+7
        self.confidence_estimator = ConfidenceEstimator()          # Mod 8
        self.dashboard_agent      = DashboardContextAgent()        # Mod 10

        print("[ReAct] Agente evolucionado listo.")

    # ──────────────────────────────────────────────────────────────────────────
    # Punto de entrada principal
    # ──────────────────────────────────────────────────────────────────────────

    def answer(self, question: str, verbose: bool = False) -> ExecutiveResponse:
        """
        Responde una pregunta de negocio usando el ciclo ReAct evolucionado.

        Args:
            question: Pregunta en lenguaje natural.
            verbose:  Si True, imprime el trazado ReAct paso a paso.

        Returns:
            ExecutiveResponse con la respuesta ejecutiva estructurada.
        """
        t_start = time.time()
        trace   = ReActTrace(question=question)

        # ─── PASO 0: Cache ───────────────────────────────────────────────────
        cached = self.memory.check_cache(question)
        if cached:
            trace.add_step("CACHE_HIT", "¿Tengo respuesta en memoria?",
                           "Consultar caché", "Respuesta encontrada en caché")
            if verbose:
                print("[ReAct] Respuesta encontrada en caché.")

        # ─── PASO 1: Análisis de intención ───────────────────────────────────
        if verbose:
            print(f"\n[ReAct] THINK: Analizando intención: '{question[:60]}'")

        intent = self.intent_agent.analyze(question)
        trace.add_step(
            "INTENT",
            f"Dominio={intent.domain}, Complejidad={intent.complexity}",
            "IntentAnalyzerAgent.analyze()",
            f"domain={intent.domain}, entities={intent.entities}, metrics={intent.metrics}",
        )
        if verbose:
            print(f"  → Dominio: {intent.domain} | Complejidad: {intent.complexity}")

        # ─── PASO 2 (Mod 2): Recuperación de memoria histórica ───────────────
        if verbose:
            print("[ReAct] ACT (Mod 2): Recuperando memoria histórica...")

        retrieved_memory = {
            "errors":    self.memory.retrieve_relevant_errors(intent.domain, top_k=3),
            "successes": self.memory.retrieve_similar_successes(
                intent.domain, intent.complexity, top_k=3
            ),
        }
        trace.add_step(
            "MEMORY_RETRIEVAL",
            "¿Hay errores o éxitos previos relevantes?",
            "MemoryAgent.retrieve_relevant_errors/successes()",
            f"Errores: {len(retrieved_memory['errors'])} | "
            f"Éxitos: {len(retrieved_memory['successes'])}",
        )

        # ─── PASO 3: Recuperación de conocimiento KB ─────────────────────────
        if verbose:
            print("[ReAct] ACT: Recuperando conocimiento empresarial...")

        kb_context     = self.kb_retriever.retrieve_formatted(question, top_k=5)
        memory_context = self.memory.format_memory_context(intent.domain, intent.complexity)

        # Enriquecer KB con memoria histórica
        enriched_context = kb_context
        if memory_context:
            enriched_context = f"{kb_context}\n\n{memory_context}"

        trace.add_step(
            "KB_RETRIEVAL",
            "¿Qué contexto empresarial necesito?",
            "BusinessKnowledgeRetriever.retrieve_formatted()",
            f"{len(kb_context)} chars KB | {len(memory_context)} chars memoria",
        )

        # ─── PASO 3.5 (Mod 10): Contexto de dashboards Power BI ──────────────
        if verbose:
            print("[ReAct] THINK (Mod 10): ¿La pregunta corresponde a algún dashboard?")

        dashboard_result = self.dashboard_agent.analyze(question, intent)
        trace.add_step(
            "DASHBOARD_CONTEXT",
            "¿Esta pregunta corresponde a datos visualizados en algún dashboard?",
            "DashboardContextAgent.analyze()",
            f"relevant={dashboard_result.is_dashboard_relevant}, "
            f"dashboards={dashboard_result.matched_dashboards}, "
            f"medidas={[m.name for m in dashboard_result.relevant_measures]}",
        )
        if verbose:
            print(f"  → Dashboard relevante: {dashboard_result.is_dashboard_relevant} "
                  f"{dashboard_result.matched_dashboards or ''}")

        if dashboard_result.is_dashboard_relevant and dashboard_result.context_text:
            # Se antepone: el contexto de dashboard es corto y de alta prioridad,
            # y otros agentes truncan enriched_context a un numero fijo de caracteres.
            enriched_context = f"{dashboard_result.context_text}\n\n{enriched_context}"

        # ─── PASO 4 (Mod 1): Validación de suficiencia de KB ─────────────────
        if verbose:
            print("[ReAct] THINK (Mod 1): ¿La KB es suficiente para responder?")

        kb_validation = self.kb_validator.validate(question, intent, enriched_context)
        trace.add_step(
            "KB_VALIDATION",
            "¿Puede responderse solo con documentación sin SQL?",
            "BusinessKnowledgeValidator.validate()",
            f"sufficient={kb_validation.is_sufficient}, confidence={kb_validation.confidence}",
        )

        if verbose:
            print(f"  → KB sufficient: {kb_validation.is_sufficient} "
                  f"({kb_validation.confidence})")

        # ─── RAMA PRINCIPAL: KB-directo o pipeline SQL ───────────────────────
        if kb_validation.is_sufficient:
            all_step_results, reflection_result, retry_count, plan = (
                self._kb_direct_path(question, intent, kb_validation, trace, verbose)
            )
            business_flags: List[str] = []
            kb_was_sufficient = True
        else:
            all_step_results, reflection_result, retry_count, plan, business_flags = (
                self._sql_pipeline(question, intent, enriched_context, trace, verbose)
            )
            kb_was_sufficient = False

        # ─── Mod 6+7: Critic Agent ────────────────────────────────────────────
        if verbose:
            print("[ReAct] THINK (Mod 6): Evaluación critica independiente...")

        critic_result, critic_iterations = self._run_critic_loop(
            question=question,
            intent=intent,
            plan=plan,
            step_results=all_step_results,
            reflection=reflection_result,
            business_flags=business_flags,
            enriched_context=enriched_context,
            trace=trace,
            verbose=verbose,
        )

        # Actualizar step_results si el critic forzó re-ejecuciones
        # (all_step_results puede haber sido actualizado dentro del loop)
        trace.add_step(
            "CRITIC",
            f"¿El análisis es suficiente? Veredicto: {critic_result.verdict}",
            "CriticAgent.evaluate()",
            f"exactness={critic_result.exactness}, "
            f"hallucination={critic_result.hallucination_risk}, "
            f"hint={critic_result.replan_hint[:60] if critic_result.replan_hint else 'none'}",
        )

        if verbose:
            print(f"  → Critic verdict: {critic_result.verdict} | "
                  f"exactness={critic_result.exactness}")

        # ─── Mod 8: Confidence Estimator ─────────────────────────────────────
        if verbose:
            print("[ReAct] COMPUTE (Mod 8): Estimando confianza compuesta...")

        confidence = self.confidence_estimator.estimate(
            step_results=all_step_results,
            reflection=reflection_result,
            critic=critic_result,
            business_flags=business_flags,
            react_iterations=retry_count + 1,
            critic_iterations=critic_iterations,
            kb_was_retrieved=True,
        )

        trace.add_step(
            "CONFIDENCE",
            "¿Cuál es el score de confianza compuesto?",
            "ConfidenceEstimator.estimate()",
            f"score={confidence.score}, action={confidence.action}, "
            f"components={confidence.components}",
        )

        if verbose:
            print(f"  → Confidence: {confidence.score}/100 ({confidence.action})")

        trace.retry_count     = retry_count
        trace.final_confidence = confidence.score
        trace.total_time_s    = time.time() - t_start

        if verbose:
            print(f"\n[ReAct] {trace.to_text()}")

        # ─── Mod 9: Formato ejecutivo ─────────────────────────────────────────
        if verbose:
            print("[ReAct] FORMAT (Mod 9): Generando respuesta ejecutiva...")

        dashboard_reference = (
            ", ".join(dashboard_result.matched_dashboards)
            if dashboard_result.is_dashboard_relevant else ""
        )

        response = self.formatter.format(
            question=question,
            intent=intent,
            plan=plan,
            step_results=all_step_results,
            reflection=reflection_result,
            business_flags=business_flags,
            confidence_estimate=confidence,
            critic=critic_result,
            kb_was_sufficient=kb_was_sufficient,
            dashboard_reference=dashboard_reference,
        )

        response.step_results = all_step_results
        response.trace_text   = trace.to_text()

        # ─── Persistir aprendizaje ────────────────────────────────────────────
        successful_sqls = [sr.sql for sr in all_step_results if sr.success]
        failed_steps    = [sr for sr in all_step_results if not sr.success]

        self.memory.record_success(
            question=question,
            domain=intent.domain,
            complexity=intent.complexity,
            plan_summary=plan.overall_approach,
            sql_snippets=successful_sqls,
            confidence=confidence.score,
        )
        for sr in failed_steps:
            self.memory.record_error(
                question=question,
                sql=sr.sql,
                error=sr.error_message or "",
                domain=intent.domain,
            )
        self.memory.cache_response(
            question=question,
            response_summary=response.executive_summary,
        )
        self.memory.save()

        return response

    # ──────────────────────────────────────────────────────────────────────────
    # Ruta KB-directo (Mod 1)
    # ──────────────────────────────────────────────────────────────────────────

    def _kb_direct_path(
        self,
        question: str,
        intent: IntentAnalysis,
        kb_validation: KBValidationResult,
        trace: ReActTrace,
        verbose: bool,
    ) -> Tuple[List[StepResult], ReflectionResult, int, AnalysisPlan]:
        """
        Ruta cuando la KB es suficiente: crea un plan de un solo paso de síntesis
        y genera un StepResult con la respuesta directa de la documentación.
        """
        if verbose:
            print("  → [Mod 1] KB suficiente: saltando pipeline SQL...")

        # Plan mínimo de síntesis
        plan = AnalysisPlan(
            question=question,
            steps=[PlanStep(
                step_number=1,
                description="Respuesta directa desde documentación empresarial",
                objective="Respuesta conceptual sin consulta BD",
                tables_hint=[],
                depends_on=[],
                sql_needed=False,
                is_synthesis=True,
            )],
            overall_approach="Respuesta directa desde knowledge base (sin SQL).",
            expected_output="Definición o explicación conceptual.",
            complexity_note="KB-directo: no requiere SQL.",
            subproblems=["Extraer respuesta de la documentación empresarial"],
        )

        # StepResult sintético con la respuesta de la KB
        kb_answer = kb_validation.answer or "Respuesta no disponible en la documentación."
        kb_step   = StepResult(
            step_number=1,
            sql="-- Respuesta directa de la knowledge base (sin SQL)",
            rows=[{"kb_answer": kb_answer}],
            columns=["kb_answer"],
            row_count=1,
            success=True,
            summary=f"KB-directo: {kb_answer[:150]}",
        )

        trace.add_step(
            "KB_DIRECT_SYNTHESIS",
            "Generando respuesta conceptual desde KB...",
            "BusinessKnowledgeValidator — síntesis directa",
            f"Respuesta KB ({len(kb_answer)} chars)",
        )

        # Reflexión sintética de alta confianza (respuesta conceptual)
        reflection = ReflectionResult(
            question_answered=True,
            confidence_score=88,
            confidence_level="normal",
            issues_found=[],
            corrections_needed=[],
            reasoning="Respuesta conceptual extraída directamente de la documentación empresarial.",
            requires_retry=False,
            retry_hint="",
            business_rules_ok=True,
            data_quality_ok=True,
        )

        return [kb_step], reflection, 0, plan

    # ──────────────────────────────────────────────────────────────────────────
    # Pipeline SQL completo (Mods 3, 4, 5)
    # ──────────────────────────────────────────────────────────────────────────

    def _sql_pipeline(
        self,
        question: str,
        intent: IntentAnalysis,
        enriched_context: str,
        trace: ReActTrace,
        verbose: bool,
    ) -> Tuple[List[StepResult], ReflectionResult, int, AnalysisPlan, List[str]]:
        """
        Pipeline SQL completo con planificación, ejecución y reflexión.
        Incorpora Mod 3 (subproblemas), Mod 4 (validacion tablas),
        Mod 5 (validacion empresarial).
        """
        if verbose:
            print("[ReAct] THINK+ACT (Mod 3): Generando plan de análisis...")

        plan = self.planner.plan(question, intent, enriched_context)
        trace.add_step(
            "PLANNING",
            f"Subproblemas: {len(plan.subproblems)} | Pasos: {len(plan.steps)}",
            "MultiHopPlanner.plan()",
            f"{plan.overall_approach[:120]}",
        )

        if verbose:
            print(f"  → Plan: {len(plan.steps)} pasos | "
                  f"Subproblemas: {plan.subproblems}")

        all_step_results:  List[StepResult] = []
        all_business_flags: List[str]       = []
        reflection_result: Optional[ReflectionResult] = None
        retry_count = 0

        for attempt in range(MAX_REACT_ITERATIONS):
            if verbose and attempt > 0:
                print(f"\n[ReAct] === REINTENTO #{attempt} ===")

            step_results, business_flags = self._execute_plan(
                plan=plan,
                question=question,
                kb_context=enriched_context,
                trace=trace,
                verbose=verbose,
            )
            all_step_results   = step_results
            all_business_flags = business_flags

            # Reflexión
            if verbose:
                print("[ReAct] REFLECT: Validando resultados...")

            reflection_result = self.reflection.reflect(
                question=question,
                intent=intent,
                step_results=step_results,
                attempt=attempt + 1,
            )

            trace.add_step(
                "REFLECTION",
                f"Confianza: {reflection_result.confidence_score}/100",
                "ReflectionAgent.reflect()",
                f"answered={reflection_result.question_answered}, "
                f"score={reflection_result.confidence_score}, "
                f"issues={reflection_result.issues_found[:2]}",
            )

            if verbose:
                print(f"  → Reflexion: {reflection_result.confidence_score}/100 "
                      f"| retry={reflection_result.requires_retry}")

            if not reflection_result.requires_retry or attempt >= MAX_REACT_ITERATIONS - 1:
                break

            # Replanificar
            retry_count += 1
            correction_ctx = (
                f"{enriched_context}\n\n"
                f"CORRECCIONES REQUERIDAS: {reflection_result.retry_hint}\n"
                f"PROBLEMAS PREVIOS: {'; '.join(reflection_result.issues_found[:3])}"
            )
            if all_business_flags:
                correction_ctx += (
                    "\nANOMALIAS EMPRESARIALES: " + " | ".join(all_business_flags[:3])
                )
            plan = self.planner.plan(question, intent, correction_ctx)

        return (
            all_step_results,
            reflection_result or self._fallback_reflection(all_step_results),
            retry_count,
            plan,
            all_business_flags,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Ejecución de pasos (Mods 4 y 5)
    # ──────────────────────────────────────────────────────────────────────────

    def _execute_plan(
        self,
        plan: AnalysisPlan,
        question: str,
        kb_context: str,
        trace: ReActTrace,
        verbose: bool,
    ) -> Tuple[List[StepResult], List[str]]:
        """
        Ejecuta todos los pasos del plan de análisis.

        Incorpora:
          Mod 4: table_validation entre select_tables y generate_sql.
          Mod 5: business_validation tras cada SQL exitoso.

        Returns:
            (step_results, business_flags_acumulados)
        """
        step_results: List[StepResult] = []
        business_flags: List[str]      = []
        prev_results_summary = ""

        for step in plan.steps:
            # Pasos de síntesis: sin SQL
            if step.is_synthesis:
                synthesis_result = StepResult(
                    step_number=step.step_number,
                    sql="-- Síntesis de pasos anteriores",
                    rows=[{"synthesis": prev_results_summary}],
                    columns=["synthesis"],
                    row_count=1,
                    success=True,
                    summary=f"Síntesis: {step.description}",
                )
                step_results.append(synthesis_result)
                continue

            # THINK: Seleccionar tablas
            if verbose:
                print(f"  [Paso {step.step_number}] THINK: Seleccionando tablas...")

            table_sel = self.table_retrieval.select_tables(
                step=step,
                question=question,
                previous_results_summary=prev_results_summary or None,
            )

            # Mod 4: Validar tablas con reintentos
            table_sel = self._validate_tables_with_retry(
                step=step,
                table_sel=table_sel,
                question=question,
                trace=trace,
                verbose=verbose,
            )

            trace.add_step(
                f"TABLE_S{step.step_number}",
                f"Tablas para: {step.description[:60]}",
                "TableRetrievalAgent + TableValidator",
                f"Seleccionadas: {', '.join(table_sel.selected_tables)}",
            )

            # THINK: Generar SQL
            if verbose:
                print(f"  [Paso {step.step_number}] THINK: Generando SQL...")

            generated_sql = self.sql_reasoning.generate(
                step=step,
                table_selection=table_sel,
                question=question,
                previous_results_summary=prev_results_summary or None,
                kb_context=kb_context,
            )

            trace.add_step(
                f"SQL_GEN_S{step.step_number}",
                f"SQL para: {step.objective[:60]}",
                "SQLReasoningAgent.generate()",
                f"SQL: {generated_sql.sql[:120]}",
            )

            # ACT: Ejecutar con reintentos SQL
            if verbose:
                print(f"  [Paso {step.step_number}] ACT: Ejecutando SQL...")

            step_result = self._execute_with_retry(
                generated_sql=generated_sql,
                table_sel=table_sel,
                step=step,
                verbose=verbose,
            )

            # Mod 5: Business validation tras SQL exitoso
            if step_result.success:
                biz_result = self.business_validator.validate(step_result, step, question)
                if biz_result.flags:
                    business_flags.extend(biz_result.flags)
                    if verbose:
                        print(f"    ⚠️  Business flags: {biz_result.flags}")

            step_results.append(step_result)

            trace.add_step(
                f"EXEC_S{step.step_number}",
                "¿El SQL produjo resultados válidos?",
                "ExecutionAgent.execute()",
                f"success={step_result.success}, rows={step_result.row_count}",
            )

            # OBSERVE: Actualizar contexto
            if step_result.success and step_result.row_count > 0:
                prev_results_summary += f"\n{step_result.summary}"

            if verbose:
                status = f"✓ {step_result.row_count} filas" if step_result.success \
                         else f"✗ {step_result.error_message}"
                print(f"    {status}")

        return step_results, business_flags

    # ──────────────────────────────────────────────────────────────────────────
    # Mod 4: Validación de tablas con reintentos
    # ──────────────────────────────────────────────────────────────────────────

    def _validate_tables_with_retry(
        self,
        step: PlanStep,
        table_sel: TableSelection,
        question: str,
        trace: ReActTrace,
        verbose: bool,
    ) -> TableSelection:
        """
        Valida la selección de tablas y reintenta select_tables si es necesario.
        Máximo MAX_TABLE_RETRIES intentos.
        """
        for attempt in range(MAX_TABLE_RETRIES + 1):
            tv_result = self.table_validator.validate(step, table_sel, question)

            if tv_result.is_valid:
                return table_sel

            if attempt >= MAX_TABLE_RETRIES:
                # Agotados los reintentos → continuar con la selección actual
                if verbose:
                    print(f"    [Mod 4] Table validation agotada tras {attempt} intentos. "
                          "Continuando con selección actual.")
                return table_sel

            # Reintento: volver a select_tables con contexto de problemas
            if verbose:
                print(f"    [Mod 4] Table validation fallo: {tv_result.issues}. "
                      f"Reintentando selección ({attempt + 1}/{MAX_TABLE_RETRIES})...")

            hint_with_issues = (
                f"{self.table_validator.format_retry_hint(tv_result)}\n"
                f"Tablas faltantes: {', '.join(tv_result.missing_tables)}"
            )
            corrected_step = PlanStep(
                step_number=step.step_number,
                description=step.description + f" [TABLE RETRY: {hint_with_issues}]",
                objective=step.objective,
                tables_hint=step.tables_hint + tv_result.missing_tables,
                depends_on=step.depends_on,
                sql_needed=step.sql_needed,
                is_synthesis=step.is_synthesis,
            )
            table_sel = self.table_retrieval.select_tables(
                step=corrected_step,
                question=question,
            )

        return table_sel

    # ──────────────────────────────────────────────────────────────────────────
    # Retry SQL
    # ──────────────────────────────────────────────────────────────────────────

    def _execute_with_retry(
        self,
        generated_sql: GeneratedSQL,
        table_sel: TableSelection,
        step: PlanStep,
        verbose: bool,
    ) -> StepResult:
        """Ejecuta SQL con hasta MAX_RETRIES_SQL intentos de corrección automática."""
        current_sql = generated_sql

        for attempt in range(MAX_RETRIES_SQL):
            result = self.execution.execute(current_sql)

            if result.success:
                return result

            if attempt < MAX_RETRIES_SQL - 1:
                if verbose:
                    print(f"    [Retry {attempt + 1}] Error: {result.error_message[:60]}")
                current_sql = self.sql_reasoning.correct(
                    sql=current_sql,
                    error_message=result.error_message or "Unknown error",
                    table_selection=table_sel,
                )

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Mod 6+7: Critic loop
    # ──────────────────────────────────────────────────────────────────────────

    def _run_critic_loop(
        self,
        question: str,
        intent: IntentAnalysis,
        plan: AnalysisPlan,
        step_results: List[StepResult],
        reflection: ReflectionResult,
        business_flags: List[str],
        enriched_context: str,
        trace: ReActTrace,
        verbose: bool,
    ) -> Tuple[CriticResult, int]:
        """
        Ejecuta el critic agent y, segun su veredicto (Mod 7), puede disparar:
          replan    → replanificar y re-ejecutar todo el pipeline
          retable   → re-ejecutar select_tables+SQL del paso N
          retry_sql → re-generar y re-ejecutar SQL del paso N

        Maximo MAX_CRITIC_ITERS iteraciones.

        Returns:
            (critic_result_final, numero_de_iteraciones_critic)
        """
        critic_result  = self.critic.evaluate(
            question, intent, plan, step_results, reflection, business_flags
        )
        critic_iters = 1

        for _ in range(MAX_CRITIC_ITERS - 1):
            if critic_result.verdict == "sufficient":
                break

            if verbose:
                print(f"  [Mod 7] Critic veredicto: {critic_result.verdict} "
                      f"(paso {critic_result.target_step}). Corrigiendo...")

            # Aplicar correccion segun veredicto
            if critic_result.verdict == "replan":
                correction_ctx = (
                    f"{enriched_context}\n\n"
                    f"CRITIC REPLAN: {critic_result.replan_hint}\n"
                    f"RAZONAMIENTO: {critic_result.reasoning}"
                )
                plan = self.planner.plan(question, intent, correction_ctx)
                step_results, business_flags = self._execute_plan(
                    plan, question, enriched_context,
                    trace, verbose,
                )
            elif critic_result.verdict in ("retable", "retry_sql"):
                # Re-ejecutar desde el paso objetivo hasta el final
                target_idx = critic_result.target_step - 1  # 0-indexed
                if 0 <= target_idx < len(plan.steps):
                    partial_results, partial_flags = self._execute_steps_from(
                        plan=plan,
                        from_step_index=target_idx,
                        question=question,
                        kb_context=enriched_context,
                        prev_results=step_results[:target_idx],
                        retry_sql_only=(critic_result.verdict == "retry_sql"),
                        trace=trace,
                        verbose=verbose,
                    )
                    # Combinar resultados previos (pasos OK antes del objetivo) con nuevos
                    step_results  = step_results[:target_idx] + partial_results
                    business_flags = business_flags + partial_flags

            reflection = self.reflection.reflect(
                question=question,
                intent=intent,
                step_results=step_results,
                attempt=critic_iters + 1,
            )
            critic_result = self.critic.evaluate(
                question, intent, plan, step_results, reflection, business_flags
            )
            critic_iters += 1

        return critic_result, critic_iters

    def _execute_steps_from(
        self,
        plan: AnalysisPlan,
        from_step_index: int,
        question: str,
        kb_context: str,
        prev_results: List[StepResult],
        retry_sql_only: bool,
        trace: ReActTrace,
        verbose: bool,
    ) -> Tuple[List[StepResult], List[str]]:
        """
        Re-ejecuta los pasos del plan a partir del índice indicado.
        Si retry_sql_only=True, salta select_tables y re-usa las tablas anteriores.
        """
        step_results: List[StepResult] = []
        business_flags: List[str]      = []
        prev_summary = "\n".join(r.summary for r in prev_results if r.success)

        for step in plan.steps[from_step_index:]:
            if step.is_synthesis:
                step_results.append(StepResult(
                    step_number=step.step_number,
                    sql="-- Síntesis",
                    rows=[{"synthesis": prev_summary}],
                    columns=["synthesis"],
                    row_count=1,
                    success=True,
                    summary=f"Síntesis: {step.description}",
                ))
                continue

            if retry_sql_only:
                # Sólo re-generar y re-ejecutar SQL con las mismas tablas
                # Recuperar la seleccion de tablas del resultado anterior si existe
                table_sel_prev = self.table_retrieval.select_tables(
                    step=step, question=question,
                    previous_results_summary=prev_summary or None,
                )
                generated = self.sql_reasoning.generate(
                    step=step,
                    table_selection=table_sel_prev,
                    question=question,
                    previous_results_summary=prev_summary or None,
                    kb_context=kb_context,
                )
                result = self._execute_with_retry(generated, table_sel_prev, step, verbose)
            else:
                # Re-ejecutar desde seleccion de tablas
                table_sel = self.table_retrieval.select_tables(
                    step=step, question=question,
                    previous_results_summary=prev_summary or None,
                )
                table_sel = self._validate_tables_with_retry(
                    step, table_sel, question, trace, verbose
                )
                generated = self.sql_reasoning.generate(
                    step=step,
                    table_selection=table_sel,
                    question=question,
                    previous_results_summary=prev_summary or None,
                    kb_context=kb_context,
                )
                result = self._execute_with_retry(generated, table_sel, step, verbose)

            if result.success:
                bv = self.business_validator.validate(result, step, question)
                business_flags.extend(bv.flags)
                prev_summary += f"\n{result.summary}"

            step_results.append(result)

        return step_results, business_flags

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _fallback_reflection(step_results: List[StepResult]) -> ReflectionResult:
        """Reflexión de fallback cuando no hay resultado de reflexión disponible."""
        failed = sum(1 for r in step_results if not r.success)
        score  = max(30, 70 - failed * 20)
        return ReflectionResult(
            question_answered=failed == 0,
            confidence_score=score,
            confidence_level="partial" if score < 70 else "limited",
            issues_found=[],
            corrections_needed=[],
            reasoning="Reflexión automática de fallback.",
            requires_retry=False,
            retry_hint="",
            business_rules_ok=True,
            data_quality_ok=failed == 0,
        )
