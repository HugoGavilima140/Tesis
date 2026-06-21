"""
agente/agents/business_validator.py — Mod 5: Business Validation Agent.

Valida que los resultados SQL son coherentes con las reglas de negocio
y los rangos esperados de PayNova inmediatamente despues de cada ejecucion SQL.

No bloquea el flujo (siempre avanza), pero registra flags que el CriticAgent
puede usar para decidir si se necesita un reintento.
"""

from dataclasses import dataclass, field
from typing import List

from agente.agents.execution import StepResult
from agente.agents.planner import PlanStep


@dataclass
class BusinessValidationResult:
    """Resultado de la validacion empresarial de un paso SQL."""
    is_valid: bool
    flags: List[str] = field(default_factory=list)
    reasoning: str = ""


# Rangos validos de metricas PayNova
_VALID_RANGES = {
    "gmv":                  (0,   500_000_000),   # hasta $500M/mes
    "monto":                (0,   500_000_000),
    "ingreso_comision":     (0,     9_000_000),   # MDR de $500M * 1.8%
    "costo_operativo":      (0,     4_000_000),
    "margen":               (0,     5_000_000),
    "monto_neto":           (-100_000_000, 500_000_000),
    "tasa_aprobacion":      (85.0,   100.0),
    "tasa_fraude":          (0.0,     10.0),
    "tasa_rechazo":         (0.0,     15.0),
    "mdr_rate":             (0.0,      5.0),
    "margen_pct":           (0.0,      3.0),
    "tasa_reactivacion":    (0.0,    100.0),
    "tasa_apertura":        (0.0,    100.0),
}


class BusinessValidator:
    """
    Valida resultados SQL contra reglas de negocio y rangos esperados.

    Mod 5: Se ejecuta entre execute_sql (exito) y advance_step.
    Siempre retorna un resultado (no lanza excepcion) para no bloquear el pipeline.
    Los flags quedan disponibles para el CriticAgent (Mod 6).
    """

    def validate(
        self,
        step_result: StepResult,
        step: PlanStep,
        question: str,
    ) -> BusinessValidationResult:
        """
        Valida los resultados del paso contra reglas de negocio PayNova.

        Args:
            step_result: Resultado de la ejecucion SQL.
            step:        Paso del plan (para contexto del objetivo).
            question:    Pregunta original (para contexto).

        Returns:
            BusinessValidationResult con flags de anomalias detectadas.
        """
        if not step_result.success:
            return BusinessValidationResult(
                is_valid=False,
                flags=[f"Paso {step_result.step_number} fallo con error: {step_result.error_message}"],
                reasoning="Paso SQL fallido, sin datos que validar.",
            )

        if not step_result.rows:
            return BusinessValidationResult(
                is_valid=False,
                flags=[
                    f"Paso {step_result.step_number}: Sin resultados — "
                    "verificar filtros WHERE, rango temporal y estado='completada'"
                ],
                reasoning="Resultado vacio puede indicar filtro incorrecto.",
            )

        flags: List[str] = []
        flags.extend(self._check_metric_ranges(step_result.rows))
        flags.extend(self._check_sql_rules(step_result.sql))
        # Incorporar anomalias ya detectadas por ExecutionAgent
        flags.extend(step_result.anomalies)

        # Deduplicar manteniendo orden
        seen = set()
        unique_flags = []
        for f in flags:
            if f not in seen:
                seen.add(f)
                unique_flags.append(f)

        return BusinessValidationResult(
            is_valid=len(unique_flags) == 0,
            flags=unique_flags,
            reasoning=(
                f"Validados {step_result.row_count} registros en paso {step_result.step_number}."
            ),
        )

    @staticmethod
    def _check_metric_ranges(rows: List[dict]) -> List[str]:
        """Detecta valores fuera de rangos esperados de metricas PayNova."""
        flags = []
        for row in rows:
            for col, (min_val, max_val) in _VALID_RANGES.items():
                val = row.get(col)
                if val is None:
                    continue
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                if v < min_val:
                    flags.append(
                        f"'{col}' = {v:,.2f} por debajo del minimo esperado ({min_val:,.2f})"
                    )
                elif v > max_val:
                    flags.append(
                        f"'{col}' = {v:,.2f} excede el maximo esperado ({max_val:,.2f})"
                    )
        return flags

    @staticmethod
    def _check_sql_rules(sql: str) -> List[str]:
        """
        Verifica el SQL generado contra reglas criticas de negocio PayNova.

        Detecta usos incorrectos conocidos sin requerir LLM.
        """
        flags = []
        if not sql:
            return flags

        sql_upper = sql.upper()

        # Regla: ingresos deben usar ingreso_comision, no SUM(monto)
        if "SUM(MONTO)" in sql_upper and (
            "INGRESO" in sql_upper or "MDR" in sql_upper or "COMISION" in sql_upper
        ):
            flags.append(
                "SQL usa SUM(monto) para calcular ingresos — "
                "debe usarse SUM(ingreso_comision) para ingresos de PayNova"
            )

        # Regla: transacciones sin filtro de estado
        if "TRANSACCIONES" in sql_upper and "ESTADO" not in sql_upper:
            flags.append(
                "Consulta sobre transacciones sin filtro estado='completada' — "
                "metricas de negocio requieren solo transacciones completadas"
            )

        # Regla: no usar DATE_TRUNC cuando hay year_month disponible
        if "DATE_TRUNC" in sql_upper and "YEAR_MONTH" not in sql_upper:
            flags.append(
                "Uso de DATE_TRUNC — considerar year_month='YYYY-MM' (mas eficiente)"
            )

        return flags
