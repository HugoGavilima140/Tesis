"""
agente/knowledge/dashboard_catalog.py — Catálogo de dashboards Power BI (Mod 10).

Indexa la estructura de los proyectos PBIP locales (páginas, visuales, tablas,
columnas y medidas DAX) para que el agente pueda:
  1. Detectar si una pregunta corresponde a información mostrada en algún dashboard.
  2. Recuperar las medidas DAX exactas y las tablas reales de PostgreSQL que las
     respaldan, para usarlas como referencia al generar el plan/SQL.

Reutiliza el parser TMDL/JSON de `mcp_powerbi/parser.py` (mismo formato PBIP,
sin credenciales ni dependencias externas).
"""

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from agente.config import DASHBOARD_ROOT, PROJECT_DIR

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import mcp_powerbi.parser as pbi  # noqa: E402

# Tablas PBIP que no corresponden a una tabla real de PostgreSQL
# (medidas, calendarios auto-generados, tablas auxiliares de gráficos).
_NON_SQL_TABLE_PREFIXES = ("LocalDateTable_", "DateTableTemplate_")
_NON_SQL_TABLE_NAMES = {"_Medidas", "TablaFunnel", "TablaWaterfall", "DimFecha"}

_SQL_SCHEMAS = {"produccion", "transacciones"}


def _normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparar términos en español de forma robusta."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", _normalize(text)) if len(t) >= 3]


def pbi_table_to_sql(table_name: str) -> Optional[str]:
    """Convierte un nombre de tabla PBIP ('produccion merchants') al identificador
    real de PostgreSQL ('produccion.merchants'). Devuelve None si no es una tabla SQL."""
    if table_name in _NON_SQL_TABLE_NAMES or table_name.startswith(_NON_SQL_TABLE_PREFIXES):
        return None
    if " " not in table_name:
        return None
    schema, rest = table_name.split(" ", 1)
    if schema not in _SQL_SCHEMAS:
        return None
    return f"{schema}.{rest}"


_QUOTED_TABLE_REF_RE = re.compile(r"'([^']+)'")


def extract_referenced_sql_tables(dax_expression: str) -> List[str]:
    """Extrae las tablas SQL reales referenciadas dentro de una expresion DAX,
    a partir de los identificadores entre comillas simples ('produccion payouts'[monto],
    COUNTROWS('produccion payouts'), etc). Las medidas casi siempre viven en una
    tabla de medidas oculta (p.ej. '_Medidas'), por lo que la tabla contenedora NO
    sirve como referencia real; hay que mirar dentro de la formula."""
    seen: List[str] = []
    for raw_name in _QUOTED_TABLE_REF_RE.findall(dax_expression or ""):
        sql_table = pbi_table_to_sql(raw_name)
        if sql_table and sql_table not in seen:
            seen.append(sql_table)
    return seen


@dataclass
class CatalogMeasure:
    name: str
    dashboard: str
    pbi_table: str
    sql_tables: List[str]   # tablas SQL reales referenciadas dentro de la expresion DAX
    expression: str
    format_string: Optional[str]
    display_folder: Optional[str]


@dataclass
class CatalogColumn:
    name: str
    dashboard: str
    pbi_table: str
    sql_table: Optional[str]
    data_type: Optional[str]


@dataclass
class CatalogVisual:
    dashboard: str
    page: str
    title: Optional[str]
    visual_type: str
    field_names: List[str] = field(default_factory=list)


@dataclass
class DashboardSearchHit:
    kind: str            # measure | column | table | visual
    dashboard: str
    label: str            # nombre de la medida/columna/página que hizo match
    detail: str            # info adicional (página, tipo de visual, etc.)
    score: int


class DashboardCatalog:
    """Catálogo en memoria de todos los dashboards PBIP disponibles bajo DASHBOARD_ROOT."""

    def __init__(self, root: Optional[Path] = None):
        self.root = root or DASHBOARD_ROOT
        self.measures: List[CatalogMeasure] = []
        self.columns: List[CatalogColumn] = []
        self.visuals: List[CatalogVisual] = []
        self.dashboards: List[str] = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if not self.root.exists():
            return

        for project in pbi.discover_projects(self.root):
            if not project.has_pbip_detail:
                continue
            self.dashboards.append(project.name)

            model = pbi.parse_semantic_model(project.semantic_model_dir)
            for table in model["tables"]:
                sql_table = pbi_table_to_sql(table["name"])
                for col in table["columns"]:
                    self.columns.append(CatalogColumn(
                        name=col["name"], dashboard=project.name,
                        pbi_table=table["name"], sql_table=sql_table,
                        data_type=col["dataType"],
                    ))
                for measure in table["measures"]:
                    self.measures.append(CatalogMeasure(
                        name=measure["name"], dashboard=project.name,
                        pbi_table=table["name"],
                        sql_tables=extract_referenced_sql_tables(measure["expression"]),
                        expression=measure["expression"],
                        format_string=measure["formatString"],
                        display_folder=measure["displayFolder"],
                    ))

            report = pbi.parse_report(project.report_dir)
            for page in report["pages"]:
                for visual in page["visuals"]:
                    field_names = [f["property"] for f in visual["fields"] if f.get("property")]
                    self.visuals.append(CatalogVisual(
                        dashboard=project.name, page=page["displayName"] or page["id"],
                        title=visual["title"], visual_type=visual["visualType"],
                        field_names=field_names,
                    ))

    def search(self, question: str, max_hits: int = 12) -> List[DashboardSearchHit]:
        """Busca términos de la pregunta contra medidas, columnas y visuales conocidos.
        Coincidencia por substring de tokens normalizados (sin acentos), sin LLM."""
        self.load()
        tokens = set(_tokenize(question))
        if not tokens:
            return []

        hits: List[DashboardSearchHit] = []

        for m in self.measures:
            name_tokens = set(_tokenize(m.name))
            overlap = tokens & name_tokens
            if not overlap and not any(t in _normalize(m.name) for t in tokens if len(t) >= 4):
                continue
            score = len(overlap) * 2 + 1
            hits.append(DashboardSearchHit(
                kind="measure", dashboard=m.dashboard, label=m.name,
                detail=f"tabla={m.pbi_table} folder={m.display_folder or '-'}",
                score=score,
            ))

        for c in self.columns:
            name_tokens = set(_tokenize(c.name))
            overlap = tokens & name_tokens
            if not overlap:
                continue
            hits.append(DashboardSearchHit(
                kind="column", dashboard=c.dashboard, label=c.name,
                detail=f"tabla={c.pbi_table}", score=len(overlap),
            ))

        for v in self.visuals:
            haystack = _normalize(f"{v.page} {v.title or ''} {' '.join(v.field_names)}")
            hay_tokens = set(re.split(r"[^a-z0-9]+", haystack))
            overlap = tokens & hay_tokens
            if not overlap:
                continue
            hits.append(DashboardSearchHit(
                kind="visual", dashboard=v.dashboard, label=v.title or v.visual_type,
                detail=f"página={v.page}", score=len(overlap),
            ))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:max_hits]

    def measures_by_name(self, names: List[str]) -> List[CatalogMeasure]:
        self.load()
        wanted = {_normalize(n) for n in names}
        seen = set()
        result = []
        for m in self.measures:
            key = _normalize(m.name)
            if key in wanted and key not in seen:
                seen.add(key)
                result.append(m)
        return result

    def pages_by_name(self, dashboards_pages: List[tuple]) -> List[CatalogVisual]:
        self.load()
        wanted = {(d, p) for d, p in dashboards_pages}
        return [v for v in self.visuals if (v.dashboard, v.page) in wanted]


_catalog_singleton: Optional[DashboardCatalog] = None


def get_dashboard_catalog() -> DashboardCatalog:
    """Instancia compartida del catálogo (se carga una sola vez por proceso)."""
    global _catalog_singleton
    if _catalog_singleton is None:
        _catalog_singleton = DashboardCatalog()
        _catalog_singleton.load()
    return _catalog_singleton
