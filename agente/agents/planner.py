"""
agente/agents/planner.py — Multi-Hop Planner Agent.

Responsabilidades:
  - Descomponer preguntas complejas en pasos de análisis.
  - Generar un plan ejecutable ANTES de escribir cualquier SQL.
  - Cada paso define: qué se consulta, por qué, qué tablas, qué produce.
  - Detectar dependencias entre pasos (un paso puede usar el resultado anterior).

El planner es el "cerebro" del sistema: sin un buen plan, el SQL estará mal.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import re
from langchain_core.messages import HumanMessage, SystemMessage

# Mod 3: importar field para subproblems

from agente.config import (
    LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, LLM_TIMEOUT, LLM_MAX_RETRIES,
    PAYNOVA_BUSINESS_RULES, MAX_SQL_STEPS,
)
from agente.agents.intent_analyzer import IntentAnalysis


def _get_llm(temperature: float = 0.0, max_tokens: int = 1024):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
        temperature=temperature, max_tokens=max_tokens,
        timeout=LLM_TIMEOUT, max_retries=LLM_MAX_RETRIES,
    )


@dataclass
class PlanStep:
    """Un paso individual del plan de análisis."""
    step_number: int
    description: str          # qué hace este paso en términos de negocio
    objective: str            # qué resultado produce
    tables_hint: List[str]    # tablas que probablemente necesita
    depends_on: List[int]     # pasos anteriores cuyo resultado usa (ej. [1, 2])
    sql_needed: bool          # ¿requiere ejecutar SQL?
    is_synthesis: bool = False  # ¿es paso de síntesis/conclusión?


@dataclass
class AnalysisPlan:
    """Plan completo de análisis multi-hop."""
    question: str
    steps: List[PlanStep]
    overall_approach: str                              # descripción narrativa del enfoque
    expected_output: str                               # qué se espera obtener al final
    complexity_note: str                               # nota sobre la complejidad del análisis
    subproblems: List[str] = field(default_factory=list)  # Mod 3: subproblemas explícitos


SYSTEM_PROMPT = """Eres un analista senior de inteligencia empresarial de PayNova S.A.

Tu tarea es diseñar un PLAN DE ANÁLISIS antes de escribir SQL.
NUNCA escribas SQL en este paso.

Contexto de negocio PayNova:
- MDR = 1.8% del monto (ingreso principal)
- Margen = 1.0% del monto (MDR - costo operativo)
- Tablas principales: transacciones.transacciones, produccion.merchants, produccion.payouts,
  produccion.notificaciones, produccion.fraude, produccion.segmentacion_merchants,
  produccion.account_managers, produccion.usuarios
""" + PAYNOVA_BUSINESS_RULES + """

Responde con un plan en este FORMATO EXACTO:

APPROACH: <descripción en 1-2 frases del enfoque general>
EXPECTED_OUTPUT: <qué información concreta se entregará al usuario>
COMPLEXITY_NOTE: <por qué este análisis tiene el nivel de complejidad indicado>

SUBPROBLEM_1: <primer subproblema a resolver>
SUBPROBLEM_2: <segundo subproblema, o NONE si no aplica>
SUBPROBLEM_3: <tercer subproblema, o NONE si no aplica>

STEP 1:
DESCRIPTION: <qué hace este paso>
OBJECTIVE: <qué resultado produce>
TABLES: <tabla1, tabla2, ...>
DEPENDS_ON: <NONE o números separados por comas: 1, 2>
SQL_NEEDED: <YES|NO>
IS_SYNTHESIS: <YES|NO>

STEP 2:
DESCRIPTION: ...
[continuar para todos los pasos necesarios]

Máximo """ + str(MAX_SQL_STEPS) + """ pasos.
Para preguntas simples: 1 paso.
Para preguntas multi-hop: 2-4 pasos.
Para análisis estratégicos: hasta 5 pasos."""


class MultiHopPlanner:
    """
    Genera planes de análisis multi-hop antes de cualquier SQL.

    Para preguntas simples: produce un plan de 1 paso.
    Para preguntas complejas: descompone en pasos con dependencias.
    """

    def __init__(self):
        self.llm = _get_llm(temperature=0.0, max_tokens=1024)

    def plan(
        self,
        question: str,
        intent: IntentAnalysis,
        kb_context: str,
    ) -> AnalysisPlan:
        """
        Genera el plan de análisis para la pregunta.

        Args:
            question:    Pregunta original del usuario.
            intent:      Análisis de intención previo.
            kb_context:  Contexto recuperado de la base de conocimiento.

        Returns:
            AnalysisPlan con todos los pasos definidos.
        """
        prompt = self._build_prompt(question, intent, kb_context)

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = self.llm.invoke(messages)
            return self._parse(response.content, question)
        except Exception as e:
            return self._fallback_plan(question, str(e))

    def _build_prompt(self, question: str, intent: IntentAnalysis, kb_context: str) -> str:
        return (
            f"Pregunta del usuario: {question}\n\n"
            f"Análisis de intención:\n"
            f"  - Dominio: {intent.domain}\n"
            f"  - Complejidad: {intent.complexity}\n"
            f"  - Entidades: {', '.join(intent.entities) or 'no especificadas'}\n"
            f"  - Métricas: {', '.join(intent.metrics) or 'no especificadas'}\n"
            f"  - Horizonte temporal: {intent.time_horizon}\n"
            f"  - Pasos SQL estimados: {intent.estimated_sql_steps}\n\n"
            f"Contexto de base de conocimiento:\n{kb_context[:1500] if kb_context else 'No disponible'}\n\n"
            f"Genera el plan de análisis:"
        )

    def _parse(self, text: str, question: str) -> AnalysisPlan:
        """Parsea la respuesta del LLM al formato AnalysisPlan."""

        def get_field(marker: str, default: str = "") -> str:
            for line in text.split("\n"):
                s = line.strip()
                if s.startswith(marker):
                    return s.split(":", 1)[1].strip() if ":" in s else default
            return default

        # Campos globales
        approach        = get_field("APPROACH:", "Análisis directo de la pregunta")
        expected_out    = get_field("EXPECTED_OUTPUT:", "Respuesta a la pregunta")
        complexity_note = get_field("COMPLEXITY_NOTE:", "")

        # Mod 3: subproblemas explícitos
        subproblems = []
        for i in range(1, 6):
            sp = get_field(f"SUBPROBLEM_{i}:", "")
            if sp and sp.upper() != "NONE":
                subproblems.append(sp)

        # Parsear pasos
        steps = self._parse_steps(text)

        if not steps:
            steps = [PlanStep(
                step_number=1,
                description="Consultar la base de datos para responder la pregunta",
                objective="Obtener los datos necesarios",
                tables_hint=[],
                depends_on=[],
                sql_needed=True,
                is_synthesis=False,
            )]

        return AnalysisPlan(
            question=question,
            steps=steps,
            overall_approach=approach,
            expected_output=expected_out,
            complexity_note=complexity_note,
            subproblems=subproblems,
        )

    def _parse_steps(self, text: str) -> List[PlanStep]:
        """Extrae los pasos STEP N: del texto."""
        steps = []
        # Dividir por bloques "STEP N:"
        step_blocks = re.split(r"STEP\s+(\d+):", text, flags=re.IGNORECASE)

        # step_blocks[0] = texto antes del primer STEP (ignorar)
        # step_blocks[1] = "1", step_blocks[2] = contenido del step 1
        # step_blocks[3] = "2", step_blocks[4] = contenido del step 2, etc.

        i = 1
        while i < len(step_blocks) - 1:
            try:
                step_num = int(step_blocks[i].strip())
                block    = step_blocks[i + 1]

                def get_in_block(marker: str, default: str = "") -> str:
                    for line in block.split("\n"):
                        s = line.strip()
                        if s.startswith(marker):
                            return s.split(":", 1)[1].strip() if ":" in s else default
                    return default

                desc     = get_in_block("DESCRIPTION:", f"Paso {step_num}")
                obj      = get_in_block("OBJECTIVE:", "")
                tables_raw = get_in_block("TABLES:", "")
                dep_raw  = get_in_block("DEPENDS_ON:", "NONE")
                sql_raw  = get_in_block("SQL_NEEDED:", "YES")
                synth_raw = get_in_block("IS_SYNTHESIS:", "NO")

                tables = [t.strip() for t in tables_raw.split(",") if t.strip() and t.upper() != "NONE"]

                depends = []
                if dep_raw.upper() not in ("NONE", ""):
                    for d in dep_raw.split(","):
                        try:
                            depends.append(int(d.strip()))
                        except ValueError:
                            pass

                steps.append(PlanStep(
                    step_number=step_num,
                    description=desc,
                    objective=obj,
                    tables_hint=tables,
                    depends_on=depends,
                    sql_needed=sql_raw.upper() == "YES",
                    is_synthesis=synth_raw.upper() == "YES",
                ))
            except (ValueError, IndexError):
                pass
            i += 2

        return steps

    def _fallback_plan(self, question: str, error: str) -> AnalysisPlan:
        """Plan mínimo de 1 paso cuando el LLM falla."""
        return AnalysisPlan(
            question=question,
            steps=[PlanStep(
                step_number=1,
                description="Consultar la base de datos para responder la pregunta",
                objective="Obtener los datos necesarios",
                tables_hint=["transacciones.transacciones"],
                depends_on=[],
                sql_needed=True,
                is_synthesis=False,
            )],
            overall_approach="Análisis directo",
            expected_output="Respuesta a la pregunta",
            complexity_note=f"Fallback: {error}",
            subproblems=[],
        )
