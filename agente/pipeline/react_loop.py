"""
agente/pipeline/react_loop.py — Orquestador ReAct del Business Reasoning Agent.

Implementa el ciclo Think → Act → Observe del paradigma ReAct.
Coordina todos los agentes en el orden correcto y maneja reintentos.

Flujo completo:
  Pregunta
    ↓ THINK: ¿Qué quiere el usuario?
  [IntentAnalyzerAgent]
    ↓ ACT: Recuperar conocimiento empresarial
  [BusinessKnowledgeRetriever]
    ↓ OBSERVE: Contexto de negocio
    ↓ THINK: ¿Hay ambigüedad? ¿Qué subproblemas hay?
  [MultiHopPlanner]
    ↓ ACT: Generar plan
    ↓ OBSERVE: Plan con N pasos
    ↓ Para cada paso:
      ↓ THINK: ¿Qué tablas necesito?
      [TableRetrievalAgent]
      ↓ THINK: ¿Qué SQL genero?
      [SQLReasoningAgent]
      ↓ ACT: Ejecutar SQL
      [ExecutionAgent]
      ↓ OBSERVE: Resultados + anomalías
    ↓ THINK: ¿Los resultados responden la pregunta?
  [ReflectionAgent]
    ↓ Si NO → retry con correcciones
    ↓ Si SÍ → formatear respuesta
  [ResponseFormatter]
    ↓ Respuesta ejecutiva
  [MemoryAgent] → persistir aprendizaje
"""

from dataclasses import dataclass, field
from typing import List, Optional
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
from agente.config import MAX_REACT_ITERATIONS, MAX_RETRIES_SQL, CONFIDENCE_THRESHOLDS


@dataclass
class ReActTrace:
    """Trazado completo de un ciclo ReAct para auditoría y debugging."""
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
            "observation": observation[:300],  # truncar para legibilidad
        })

    def to_text(self) -> str:
        lines = [f"=== ReAct Trace: {self.question[:80]} ==="]
        for i, step in enumerate(self.iterations, 1):
            lines.append(f"\n[{i}] {step['phase'].upper()}")
            lines.append(f"  THOUGHT: {step['thought']}")
            lines.append(f"  ACTION:  {step['action']}")
            lines.append(f"  OBSERVE: {step['observation']}")
        lines.append(f"\nConfianza final: {self.final_confidence}/100 | Reintentos: {self.retry_count}")
        lines.append(f"Tiempo total: {self.total_time_s:.1f}s")
        return "\n".join(lines)


class BusinessReasoningAgent:
    """
    Agente de Razonamiento Empresarial con arquitectura ReAct + Multi-Hop.

    Integra todos los subagentes en un flujo coherente de razonamiento,
    planificación, ejecución y reflexión para responder preguntas de negocio.
    """

    def __init__(self, force_rebuild_kb: bool = False):
        print("[ReAct] Inicializando Business Reasoning Agent...")

        # Inicializar KB
        self.kb_retriever = BusinessKnowledgeRetriever()
        self.kb_retriever.initialize(force_rebuild=force_rebuild_kb)

        # Inicializar agentes
        self.intent_agent    = IntentAnalyzerAgent()
        self.planner         = MultiHopPlanner()
        self.table_retrieval = TableRetrievalAgent()
        self.sql_reasoning   = SQLReasoningAgent()
        self.execution       = ExecutionAgent()
        self.reflection      = ReflectionAgent()
        self.memory          = MemoryAgent()
        self.formatter       = ResponseFormatter()

        print("[ReAct] Agente listo.")

    def answer(self, question: str, verbose: bool = False) -> ExecutiveResponse:
        """
        Responde una pregunta de negocio usando el ciclo ReAct completo.

        Args:
            question: Pregunta en lenguaje natural (español preferido).
            verbose:  Si True, imprime el trazado ReAct paso a paso.

        Returns:
            ExecutiveResponse con la respuesta ejecutiva estructurada.
        """
        t_start = time.time()
        trace = ReActTrace(question=question)

        # ─── PASO 0: Verificar caché de memoria ─────────────────────────────
        cached = self.memory.check_cache(question)
        if cached:
            trace.add_step("CACHE_HIT", "¿Tengo esta respuesta en memoria?",
                          "Consultar caché", f"Respuesta encontrada en caché")
            if verbose:
                print("[ReAct] Respuesta encontrada en caché.")
            # Devolver nota de caché (el usuario puede querer actualizar)

        # ─── PASO 1: THINK — Análisis de intención ──────────────────────────
        if verbose:
            print(f"\n[ReAct] THINK: Analizando intención de: '{question[:60]}...'")

        intent = self.intent_agent.analyze(question)
        trace.add_step(
            "INTENT",
            f"¿Qué quiere el usuario? Dominio={intent.domain}, Complejidad={intent.complexity}",
            "IntentAnalyzerAgent.analyze()",
            f"domain={intent.domain}, type={intent.query_type}, entities={intent.entities}",
        )

        if verbose:
            print(f"  → Dominio: {intent.domain} | Complejidad: {intent.complexity}")
            if intent.is_ambiguous:
                print(f"  ⚠️  Ambigüedad detectada: {intent.ambiguity_reason}")

        # ─── PASO 2: ACT — Recuperar conocimiento empresarial ────────────────
        if verbose:
            print("[ReAct] ACT: Recuperando conocimiento de la KB...")

        kb_context = self.kb_retriever.retrieve_formatted(question, top_k=5)
        memory_context = self.memory.format_memory_context(intent.domain, intent.complexity)

        trace.add_step(
            "KB_RETRIEVAL",
            "¿Qué contexto de negocio necesito?",
            "BusinessKnowledgeRetriever.retrieve_formatted()",
            f"Recuperados {len(kb_context)} chars de la KB",
        )

        # Combinar KB + memoria
        enriched_context = kb_context
        if memory_context:
            enriched_context = f"{kb_context}\n\n{memory_context}"

        # ─── PASO 3: THINK — Manejar ambigüedad ─────────────────────────────
        if intent.is_ambiguous and verbose:
            print(f"  [ReAct] Ambigüedad: {intent.ambiguity_reason}")
            print("  [ReAct] Continuando con interpretación más probable...")

        # ─── PASO 4: THINK+ACT — Generar plan Multi-Hop ─────────────────────
        if verbose:
            print("[ReAct] THINK+ACT: Generando plan de análisis...")

        plan = self.planner.plan(question, intent, enriched_context)
        trace.add_step(
            "PLANNING",
            f"¿Qué subproblemas debo resolver? Estimado: {intent.estimated_sql_steps} pasos",
            "MultiHopPlanner.plan()",
            f"Plan con {len(plan.steps)} pasos: {plan.overall_approach[:100]}",
        )

        if verbose:
            print(f"  → Plan: {len(plan.steps)} pasos")
            for step in plan.steps:
                print(f"    {step.step_number}. {step.description[:70]}")

        # ─── LOOP REACT: Ejecutar pasos + reflexión + retry ──────────────────
        all_step_results: List[StepResult] = []
        reflection_result: Optional[ReflectionResult] = None
        retry_count = 0

        for attempt in range(MAX_REACT_ITERATIONS):
            if verbose and attempt > 0:
                print(f"\n[ReAct] === REINTENTO #{attempt} ===")

            # Ejecutar todos los pasos del plan
            step_results = self._execute_plan(
                plan=plan,
                question=question,
                kb_context=enriched_context,
                trace=trace,
                verbose=verbose,
            )
            all_step_results = step_results

            # ─── REFLECT ────────────────────────────────────────────────────
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
                f"¿Los resultados responden la pregunta? Confianza: {reflection_result.confidence_score}",
                "ReflectionAgent.reflect()",
                f"answered={reflection_result.question_answered}, "
                f"score={reflection_result.confidence_score}, "
                f"issues={reflection_result.issues_found[:2]}",
            )

            if verbose:
                print(f"  → Confianza: {reflection_result.confidence_score}/100")
                if reflection_result.issues_found:
                    print(f"  → Problemas: {reflection_result.issues_found}")

            # ¿Aceptar resultado?
            if not reflection_result.requires_retry or attempt >= MAX_REACT_ITERATIONS - 1:
                break

            # ─── REPLANNING ─────────────────────────────────────────────────
            retry_count += 1
            if verbose:
                print(f"  [ReAct] Replanificando por: {reflection_result.retry_hint}")

            # Re-generar plan con pistas de corrección
            correction_context = (
                f"{enriched_context}\n\n"
                f"CORRECCIONES REQUERIDAS: {reflection_result.retry_hint}\n"
                f"PROBLEMAS PREVIOS: {'; '.join(reflection_result.issues_found[:3])}"
            )
            plan = self.planner.plan(question, intent, correction_context)

        trace.retry_count = retry_count
        trace.final_confidence = reflection_result.confidence_score if reflection_result else 0
        trace.total_time_s = time.time() - t_start

        if verbose:
            print(f"\n[ReAct] {trace.to_text()}")

        # ─── FORMAT: Generar respuesta ejecutiva ─────────────────────────────
        if verbose:
            print("[ReAct] FORMAT: Generando respuesta ejecutiva...")

        response = self.formatter.format(
            question=question,
            intent=intent,
            plan=plan,
            step_results=all_step_results,
            reflection=reflection_result,
        )

        # Adjuntar datos de debug para la UI de Streamlit
        response.step_results = all_step_results
        response.trace_text   = trace.to_text()

        # ─── MEMORY: Persistir aprendizaje ───────────────────────────────────
        successful_sqls = [
            sr.sql for sr in all_step_results if sr.success
        ]
        failed_steps = [sr for sr in all_step_results if not sr.success]

        self.memory.record_success(
            question=question,
            domain=intent.domain,
            complexity=intent.complexity,
            plan_summary=plan.overall_approach,
            sql_snippets=successful_sqls,
            confidence=response.confidence_score,
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

    def _execute_plan(
        self,
        plan: AnalysisPlan,
        question: str,
        kb_context: str,
        trace: ReActTrace,
        verbose: bool,
    ) -> List[StepResult]:
        """
        Ejecuta todos los pasos del plan de análisis.

        Para cada paso:
          THINK  → seleccionar tablas
          THINK  → generar SQL
          ACT    → ejecutar SQL
          OBSERVE → registrar resultado
        """
        step_results: List[StepResult] = []
        prev_results_summary = ""

        for step in plan.steps:
            if step.is_synthesis:
                # Paso de síntesis: no ejecuta SQL, usa resultados anteriores
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

            # THINK: ¿Qué tablas necesito?
            if verbose:
                print(f"  [Paso {step.step_number}] THINK: Seleccionando tablas...")

            table_sel = self.table_retrieval.select_tables(
                step=step,
                question=question,
                previous_results_summary=prev_results_summary if prev_results_summary else None,
            )

            trace.add_step(
                f"TABLE_RETRIEVAL_S{step.step_number}",
                f"¿Qué tablas necesito para: {step.description[:60]}?",
                "TableRetrievalAgent.select_tables()",
                f"Seleccionadas: {', '.join(table_sel.selected_tables)}",
            )

            # THINK: ¿Qué SQL genero?
            if verbose:
                print(f"  [Paso {step.step_number}] THINK: Generando SQL...")
                print(f"    Tablas: {', '.join(table_sel.selected_tables)}")

            generated_sql = self.sql_reasoning.generate(
                step=step,
                table_selection=table_sel,
                question=question,
                previous_results_summary=prev_results_summary if prev_results_summary else None,
                kb_context=kb_context,
            )

            trace.add_step(
                f"SQL_GEN_S{step.step_number}",
                f"¿Qué SQL resuelve: {step.objective[:60]}?",
                f"SQLReasoningAgent.generate()",
                f"SQL: {generated_sql.sql[:120]}",
            )

            # ACT: Ejecutar SQL con reintentos
            if verbose:
                print(f"  [Paso {step.step_number}] ACT: Ejecutando SQL...")
                print(f"    {generated_sql.sql[:80]}...")

            step_result = self._execute_with_retry(
                generated_sql=generated_sql,
                table_sel=table_sel,
                step=step,
                verbose=verbose,
            )
            step_results.append(step_result)

            trace.add_step(
                f"EXEC_S{step.step_number}",
                f"¿El SQL produjo resultados válidos?",
                "ExecutionAgent.execute()",
                f"success={step_result.success}, rows={step_result.row_count}, "
                f"anomalies={step_result.anomalies[:1]}",
            )

            # OBSERVE: Actualizar contexto para el siguiente paso
            if step_result.success and step_result.row_count > 0:
                prev_results_summary += f"\n{step_result.summary}"

            if verbose:
                if step_result.success:
                    print(f"    ✓ {step_result.row_count} filas obtenidas")
                    if step_result.anomalies:
                        print(f"    ⚠️  Anomalías: {step_result.anomalies}")
                else:
                    print(f"    ✗ Error: {step_result.error_message}")

        return step_results

    def _execute_with_retry(
        self,
        generated_sql: GeneratedSQL,
        table_sel: TableSelection,
        step: PlanStep,
        verbose: bool,
    ) -> StepResult:
        """Ejecuta el SQL con reintentos automáticos en caso de error."""
        current_sql = generated_sql

        for attempt in range(MAX_RETRIES_SQL):
            result = self.execution.execute(current_sql)

            if result.success:
                return result

            # Falló → intentar corrección
            if attempt < MAX_RETRIES_SQL - 1:
                if verbose:
                    print(f"    [Retry {attempt+1}] Error: {result.error_message[:60]}")
                current_sql = self.sql_reasoning.correct(
                    sql=current_sql,
                    error_message=result.error_message or "Unknown error",
                    table_selection=table_sel,
                )

        # Todos los reintentos fallaron
        return result
