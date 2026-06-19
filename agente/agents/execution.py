"""
agente/agents/execution.py — Execution Agent para PostgreSQL.

Responsabilidades:
  - Conectar a la base de datos PostgreSQL de PayNova.
  - Ejecutar queries SELECT de forma segura (read-only).
  - Detectar errores SQL y resultados vacíos.
  - Detectar anomalías en los resultados (valores fuera de rango esperado).
  - Resumir resultados para consumo por el Reflection Agent.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import re

from agente.config import PG_URL, PAYNOVA_TABLES
from agente.agents.sql_reasoning import GeneratedSQL


@dataclass
class StepResult:
    """Resultado de ejecutar un paso del plan."""
    step_number: int
    sql: str
    rows: Optional[List[Dict[str, Any]]]   # filas como lista de dicts
    columns: Optional[List[str]]
    row_count: int
    success: bool
    error_message: Optional[str] = None
    anomalies: List[str] = field(default_factory=list)
    summary: str = ""  # resumen textual para el Reflection Agent


# Rangos de validación para detectar anomalías
ANOMALY_RANGES = {
    "tasa_aprobacion": (85.0, 100.0),
    "tasa_rechazo": (0.0, 20.0),
    "tasa_fraude": (0.0, 10.0),
    "mdr_rate": (0.0, 5.0),
    "margen_pct": (0.0, 3.0),
    "row_count_max": 10_000_000,
}


class ExecutionAgent:
    """
    Ejecuta SQL contra la base de datos PostgreSQL de PayNova.

    Implementa ejecución segura (read-only), detección de errores,
    detección de anomalías y summarización de resultados.
    """

    MAX_ROWS = 500  # límite de filas a recuperar

    def __init__(self):
        self._engine = None

    def _get_engine(self):
        """Crea/reutiliza la conexión SQLAlchemy al PostgreSQL."""
        if self._engine is None:
            try:
                from sqlalchemy import create_engine, text as sa_text
                self._engine = create_engine(
                    PG_URL,
                    pool_pre_ping=True,
                    connect_args={"connect_timeout": 30},
                )
                # Test de conexión
                with self._engine.connect() as conn:
                    conn.execute(sa_text("SELECT 1"))
            except Exception as e:
                self._engine = None
                raise RuntimeError(f"No se pudo conectar a PostgreSQL: {e}")
        return self._engine

    def execute(self, generated: GeneratedSQL) -> StepResult:
        """
        Ejecuta el SQL del paso generado.

        Args:
            generated: GeneratedSQL con el SQL a ejecutar.

        Returns:
            StepResult con filas, columnas y análisis de anomalías.
        """
        sql = generated.sql.strip()

        # Validación de seguridad: solo SELECT
        if not self._is_safe_sql(sql):
            return StepResult(
                step_number=generated.step_number,
                sql=sql,
                rows=None,
                columns=None,
                row_count=0,
                success=False,
                error_message="Solo se permiten queries SELECT en modo de análisis.",
            )

        # SQL vacío
        if not sql or sql == ";":
            return StepResult(
                step_number=generated.step_number,
                sql=sql,
                rows=None,
                columns=None,
                row_count=0,
                success=False,
                error_message="SQL vacío generado.",
            )

        try:
            engine = self._get_engine()
        except RuntimeError as e:
            return StepResult(
                step_number=generated.step_number,
                sql=sql,
                rows=None,
                columns=None,
                row_count=0,
                success=False,
                error_message=str(e),
            )

        try:
            from sqlalchemy import text as sa_text
            with engine.connect() as conn:
                result = conn.execute(sa_text(sql))
                cols = list(result.keys())
                raw_rows = result.fetchmany(self.MAX_ROWS)

            rows = [dict(zip(cols, row)) for row in raw_rows]

            # Convertir tipos no JSON-serializables
            rows = self._normalize_rows(rows)

            # Detectar anomalías
            anomalies = self._detect_anomalies(rows, cols, sql)

            # Generar resumen
            summary = self._summarize(rows, cols, generated.step_number)

            return StepResult(
                step_number=generated.step_number,
                sql=sql,
                rows=rows,
                columns=cols,
                row_count=len(rows),
                success=True,
                anomalies=anomalies,
                summary=summary,
            )

        except Exception as e:
            return StepResult(
                step_number=generated.step_number,
                sql=sql,
                rows=None,
                columns=None,
                row_count=0,
                success=False,
                error_message=str(e)[:500],
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Internos
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_safe_sql(sql: str) -> bool:
        """Verifica que el SQL sea un SELECT puro."""
        cleaned = sql.strip().lstrip("-").strip()
        upper   = cleaned.upper()
        # Permitir: SELECT, WITH (CTEs que terminan en SELECT)
        if upper.startswith("SELECT") or upper.startswith("WITH"):
            # Asegurar que no hay DML/DDL
            dangerous = re.compile(
                r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b",
                re.IGNORECASE,
            )
            return not dangerous.search(sql)
        return False

    @staticmethod
    def _normalize_rows(rows: List[Dict]) -> List[Dict]:
        """Convierte tipos Python no serializables a tipos básicos."""
        import decimal
        import datetime

        normalized = []
        for row in rows:
            new_row = {}
            for k, v in row.items():
                if isinstance(v, decimal.Decimal):
                    new_row[k] = float(v)
                elif isinstance(v, (datetime.date, datetime.datetime)):
                    new_row[k] = str(v)
                elif v is None:
                    new_row[k] = None
                else:
                    new_row[k] = v
            normalized.append(new_row)
        return normalized

    @staticmethod
    def _detect_anomalies(
        rows: List[Dict], cols: List[str], sql: str
    ) -> List[str]:
        """Detecta valores fuera de rangos esperados."""
        anomalies = []

        if not rows:
            anomalies.append("El resultado está vacío — puede indicar un filtro incorrecto.")
            return anomalies

        # Detectar porcentajes fuera de rango
        pct_cols = [c for c in cols if any(x in c.lower() for x in ["tasa", "pct", "rate", "ratio"])]
        for col in pct_cols:
            vals = [r[col] for r in rows if r.get(col) is not None]
            if vals:
                avg_val = sum(vals) / len(vals)
                if avg_val > 100:
                    anomalies.append(f"'{col}' promedio={avg_val:.1f}% — valor > 100%, revisar si es porcentaje o decimal.")
                elif avg_val < 0:
                    anomalies.append(f"'{col}' promedio={avg_val:.4f} — valor negativo, revisar cálculo.")

        # Detectar GMV o montos negativos
        money_cols = [c for c in cols if any(x in c.lower() for x in ["gmv", "monto", "margen", "ingreso", "costo"])]
        for col in money_cols:
            vals = [r[col] for r in rows if r.get(col) is not None]
            neg = [v for v in vals if isinstance(v, (int, float)) and v < 0]
            if neg:
                anomalies.append(f"'{col}' tiene {len(neg)} valores negativos — revisar si es esperado.")

        return anomalies

    @staticmethod
    def _summarize(rows: List[Dict], cols: List[str], step_num: int) -> str:
        """Genera un resumen textual del resultado para el Reflection Agent."""
        if not rows:
            return f"Paso {step_num}: Sin resultados."

        n = len(rows)
        sample = rows[0]

        # Resumen de la primera fila
        sample_str = ", ".join(f"{k}={v}" for k, v in list(sample.items())[:5])

        if n == 1:
            return f"Paso {step_num}: 1 resultado → {sample_str}"
        else:
            return f"Paso {step_num}: {n} filas. Primera fila: {sample_str}"
