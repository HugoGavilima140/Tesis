"""Parsing de proyectos Power BI en formato PBIP (TMDL + JSON) sin dependencias externas."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1].replace("''", "'")
    return name


# ---------------------------------------------------------------------------
# TMDL parsing (tablas, columnas, medidas, relaciones)
# ---------------------------------------------------------------------------

_TABLE_RE = re.compile(r"^table\s+(.+)$")
_COLUMN_RE = re.compile(r"^\tcolumn\s+(.+)$")
_MEASURE_RE = re.compile(r"^\tmeasure\s+('(?:[^']|'')+'|[^\s=]+)\s*=\s*(.*)$")
_HIERARCHY_RE = re.compile(r"^\thierarchy\s+(.+)$")
_PARTITION_RE = re.compile(r"^\tpartition\s+(.+)$")
_PROP_RE = re.compile(r"^\t\t([A-Za-z][A-Za-z0-9_]*):\s*(.*)$")
_RELATIONSHIP_RE = re.compile(r"^relationship\s+(.+)$")
_REL_PROP_RE = re.compile(r"^\t([A-Za-z][A-Za-z0-9_]*):\s*(.*)$")


def parse_table_tmdl(path: Path) -> dict:
    """Parsea un archivo .tmdl de tabla: columnas y medidas."""
    lines = path.read_text(encoding="utf-8-sig").split("\n")
    table_name = path.stem
    is_hidden = False
    columns: list[dict] = []
    measures: list[dict] = []

    current: dict | None = None
    current_kind: str | None = None  # "column" | "measure"

    def flush():
        if current is None:
            return
        if current_kind == "column":
            columns.append(current)
        elif current_kind == "measure":
            measures.append(current)

    for raw in lines:
        line = raw.rstrip("\r")
        if not line.strip():
            continue

        m = _TABLE_RE.match(line)
        if m:
            table_name = _unquote(m.group(1))
            continue

        if line == "\tisHidden":
            is_hidden = True
            continue

        m = _COLUMN_RE.match(line)
        if m:
            flush()
            current = {"name": _unquote(m.group(1)), "dataType": None, "isHidden": False, "displayFolder": None}
            current_kind = "column"
            continue

        m = _MEASURE_RE.match(line)
        if m:
            flush()
            current = {
                "name": _unquote(m.group(1)),
                "expression": m.group(2).strip(),
                "formatString": None,
                "displayFolder": None,
            }
            current_kind = "measure"
            continue

        m = _HIERARCHY_RE.match(line)
        if m:
            flush()
            current = None
            current_kind = None
            continue

        m = _PARTITION_RE.match(line)
        if m:
            flush()
            current = None
            current_kind = None
            continue

        m = _PROP_RE.match(line)
        if m and current is not None:
            key, value = m.group(1), m.group(2).strip()
            if key == "dataType" and current_kind == "column":
                current["dataType"] = value
            elif key == "isHidden":
                current["isHidden"] = True
            elif key == "displayFolder":
                current["displayFolder"] = _unquote(value)
            elif key == "formatString" and current_kind == "measure":
                current["formatString"] = value

    flush()
    return {"name": table_name, "isHidden": is_hidden, "columns": columns, "measures": measures}


def parse_relationships_tmdl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8-sig").split("\n")
    relationships: list[dict] = []
    current: dict | None = None

    def flush():
        if current is not None:
            relationships.append(current)

    for raw in lines:
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        m = _RELATIONSHIP_RE.match(line)
        if m:
            flush()
            current = {"id": m.group(1).strip(), "fromColumn": None, "toColumn": None, "crossFilteringBehavior": "single"}
            continue
        m = _REL_PROP_RE.match(line)
        if m and current is not None:
            key, value = m.group(1), m.group(2).strip()
            if key in ("fromColumn", "toColumn"):
                current[key] = value
            elif key == "crossFilteringBehavior":
                current["crossFilteringBehavior"] = value
    flush()
    return relationships


def parse_semantic_model(semantic_model_dir: Path) -> dict:
    tables_dir = semantic_model_dir / "definition" / "tables"
    tables = []
    if tables_dir.exists():
        for tmdl_file in sorted(tables_dir.glob("*.tmdl")):
            tables.append(parse_table_tmdl(tmdl_file))
    relationships = parse_relationships_tmdl(semantic_model_dir / "definition" / "relationships.tmdl")
    return {"tables": tables, "relationships": relationships}


# ---------------------------------------------------------------------------
# Report JSON parsing (páginas y visuales)
# ---------------------------------------------------------------------------

def _find_fields(node, found: list[dict]):
    """Recorre recursivamente un dict/list buscando referencias a Measure/Column con Entity+Property."""
    if isinstance(node, dict):
        for kind in ("Measure", "Column"):
            if kind in node and isinstance(node[kind], dict):
                inner = node[kind]
                prop = inner.get("Property")
                entity = None
                expr = inner.get("Expression", {})
                if isinstance(expr, dict):
                    source_ref = expr.get("SourceRef", {})
                    if isinstance(source_ref, dict):
                        entity = source_ref.get("Entity") or source_ref.get("Schema")
                if prop is not None:
                    ref = {"kind": kind, "entity": entity, "property": prop}
                    if ref not in found:
                        found.append(ref)
        for value in node.values():
            _find_fields(value, found)
    elif isinstance(node, list):
        for item in node:
            _find_fields(item, found)


def _extract_title(visual: dict) -> str | None:
    try:
        title_objs = visual["visual"]["visualContainerObjects"]["title"]
        for obj in title_objs:
            text = obj.get("properties", {}).get("text", {}).get("expr", {}).get("Literal", {}).get("Value")
            if text:
                return _unquote(text)
    except (KeyError, TypeError):
        pass
    return None


def parse_visual(visual_path: Path) -> dict:
    data = json.loads(visual_path.read_text(encoding="utf-8-sig"))
    visual = data.get("visual", {})
    fields: list[dict] = []
    _find_fields(visual.get("query", {}), fields)
    return {
        "name": data.get("name"),
        "visualType": visual.get("visualType"),
        "title": _extract_title(data),
        "fields": fields,
    }


def parse_page(page_dir: Path) -> dict:
    page_json = json.loads((page_dir / "page.json").read_text(encoding="utf-8-sig"))
    visuals = []
    visuals_dir = page_dir / "visuals"
    if visuals_dir.exists():
        for visual_dir in sorted(visuals_dir.iterdir()):
            visual_file = visual_dir / "visual.json"
            if visual_file.exists():
                visuals.append(parse_visual(visual_file))
    return {
        "id": page_json.get("name"),
        "displayName": page_json.get("displayName"),
        "visualCount": len(visuals),
        "visuals": visuals,
    }


def parse_report(report_dir: Path) -> dict:
    pages_dir = report_dir / "definition" / "pages"
    order_file = pages_dir / "pages.json"
    order = []
    if order_file.exists():
        order = json.loads(order_file.read_text(encoding="utf-8-sig")).get("pageOrder", [])

    pages_by_id = {}
    if pages_dir.exists():
        for page_dir in pages_dir.iterdir():
            if page_dir.is_dir():
                page = parse_page(page_dir)
                pages_by_id[page["id"]] = page

    ordered_pages = [pages_by_id[pid] for pid in order if pid in pages_by_id]
    for pid, page in pages_by_id.items():
        if pid not in order:
            ordered_pages.append(page)

    return {"pages": ordered_pages}


# ---------------------------------------------------------------------------
# Descubrimiento de proyectos PBIP
# ---------------------------------------------------------------------------

@dataclass
class ReportProject:
    name: str
    root: Path
    report_dir: Path | None
    semantic_model_dir: Path | None
    loose_pbix: list[str] = field(default_factory=list)

    @property
    def has_pbip_detail(self) -> bool:
        return self.report_dir is not None and self.semantic_model_dir is not None


def discover_projects(root: Path) -> list[ReportProject]:
    """Encuentra proyectos *.pbip (con .Report / .SemanticModel) y archivos .pbix sueltos."""
    projects: dict[str, ReportProject] = {}

    for pbip_file in root.glob("*.pbip"):
        name = pbip_file.stem
        report_dir = root / f"{name}.Report"
        semantic_dir = root / f"{name}.SemanticModel"
        projects[name] = ReportProject(
            name=name,
            root=root,
            report_dir=report_dir if report_dir.exists() else None,
            semantic_model_dir=semantic_dir if semantic_dir.exists() else None,
        )

    for pbix_file in root.glob("*.pbix"):
        name = pbix_file.stem
        if name in projects:
            continue
        projects.setdefault(
            name, ReportProject(name=name, root=root, report_dir=None, semantic_model_dir=None)
        ).loose_pbix.append(pbix_file.name)

    return sorted(projects.values(), key=lambda p: p.name)
