"""Servidor MCP que expone la estructura de reportes Power BI (formato PBIP local).

Lee directamente las carpetas *.Report (TMDL/JSON de páginas y visuales) y
*.SemanticModel (TMDL de tablas, columnas, medidas DAX y relaciones) sin
necesidad de credenciales ni conexión a Power BI Service.
"""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import parser as pbi

ROOT = Path(os.environ.get("POWERBI_ROOT", Path(__file__).resolve().parent.parent / "Dashboard Ejecutivos"))

mcp = FastMCP("powerbi-structure")


def _get_project(report_name: str) -> pbi.ReportProject:
    projects = {p.name: p for p in pbi.discover_projects(ROOT)}
    if report_name not in projects:
        available = ", ".join(sorted(projects)) or "(ninguno)"
        raise ValueError(f"Reporte '{report_name}' no encontrado. Disponibles: {available}")
    return projects[report_name]


@mcp.tool()
def list_reports() -> dict:
    """Lista los reportes de Power BI encontrados bajo el directorio raíz configurado.

    Indica cuáles tienen estructura PBIP completa (páginas, visuales, modelo semántico
    legible) y cuáles son solo archivos .pbix binarios sin detalle navegable.
    """
    projects = pbi.discover_projects(ROOT)
    return {
        "root": str(ROOT),
        "reports": [
            {
                "name": p.name,
                "has_pbip_detail": p.has_pbip_detail,
                "loose_pbix_files": p.loose_pbix,
                "note": None
                if p.has_pbip_detail
                else "Solo .pbix binario: abre en Power BI Desktop y usa 'Guardar como > Power BI project (.pbip)' para exponer su estructura aquí.",
            }
            for p in projects
        ],
    }


@mcp.tool()
def get_report_overview(report_name: str) -> dict:
    """Resumen de un reporte: páginas con sus títulos de visuales, tablas del modelo
    y medidas agrupadas por carpeta de visualización (displayFolder). Punto de partida
    ideal para entender de un vistazo qué muestra un reporte."""
    project = _get_project(report_name)
    if not project.has_pbip_detail:
        return {"error": f"'{report_name}' no tiene estructura PBIP (.Report/.SemanticModel)."}

    report = pbi.parse_report(project.report_dir)
    model = pbi.parse_semantic_model(project.semantic_model_dir)

    pages_summary = [
        {
            "id": pg["id"],
            "displayName": pg["displayName"],
            "visual_titles": [v["title"] or v["visualType"] for v in pg["visuals"]],
        }
        for pg in report["pages"]
    ]

    tables_summary = [
        {"name": t["name"], "isHidden": t["isHidden"], "column_count": len(t["columns"])}
        for t in model["tables"]
        if not t["name"].startswith(("LocalDateTable_", "DateTableTemplate_"))
    ]

    measures_by_folder: dict[str, list[str]] = {}
    for t in model["tables"]:
        for m in t["measures"]:
            folder = m["displayFolder"] or "(sin carpeta)"
            measures_by_folder.setdefault(folder, []).append(m["name"])

    return {"pages": pages_summary, "tables": tables_summary, "measures_by_folder": measures_by_folder}


@mcp.tool()
def get_pages(report_name: str) -> list[dict]:
    """Lista las páginas de un reporte con su id interno y displayName visible al usuario."""
    project = _get_project(report_name)
    if not project.has_pbip_detail:
        return [{"error": f"'{report_name}' no tiene estructura PBIP."}]
    report = pbi.parse_report(project.report_dir)
    return [{"id": pg["id"], "displayName": pg["displayName"], "visualCount": pg["visualCount"]} for pg in report["pages"]]


@mcp.tool()
def get_page_detail(report_name: str, page: str) -> dict:
    """Detalle completo de una página: cada visual con su tipo, título y los campos
    (medidas/columnas de qué tabla) que utiliza. `page` acepta el id interno o el
    displayName de la página."""
    project = _get_project(report_name)
    if not project.has_pbip_detail:
        return {"error": f"'{report_name}' no tiene estructura PBIP."}
    report = pbi.parse_report(project.report_dir)
    for pg in report["pages"]:
        if pg["id"] == page or pg["displayName"] == page:
            return pg
    names = [pg["displayName"] for pg in report["pages"]]
    return {"error": f"Página '{page}' no encontrada. Disponibles: {names}"}


@mcp.tool()
def get_semantic_model(report_name: str) -> dict:
    """Modelo semántico completo: tablas con sus columnas (nombre, tipo de dato,
    si están ocultas) y medidas DAX (nombre, expresión, formato, carpeta), más
    las relaciones entre tablas."""
    project = _get_project(report_name)
    if not project.has_pbip_detail:
        return {"error": f"'{report_name}' no tiene estructura PBIP."}
    return pbi.parse_semantic_model(project.semantic_model_dir)


@mcp.tool()
def get_measure(report_name: str, measure_name: str) -> dict:
    """Busca una medida DAX por nombre exacto o parcial (case-insensitive) y devuelve
    su expresión completa, formato y tabla contenedora."""
    project = _get_project(report_name)
    if not project.has_pbip_detail:
        return {"error": f"'{report_name}' no tiene estructura PBIP."}
    model = pbi.parse_semantic_model(project.semantic_model_dir)
    term = measure_name.lower()
    matches = []
    for t in model["tables"]:
        for m in t["measures"]:
            if term in m["name"].lower():
                matches.append({**m, "table": t["name"]})
    if not matches:
        return {"error": f"No se encontró ninguna medida que contenga '{measure_name}'."}
    return {"matches": matches}


@mcp.tool()
def search_field(report_name: str, term: str) -> dict:
    """Busca un término en nombres de columnas/medidas del modelo y en los campos
    usados por visuales, devolviendo en qué páginas/visuales aparece. Útil para
    responder '¿dónde se usa el campo X en este reporte?'."""
    project = _get_project(report_name)
    if not project.has_pbip_detail:
        return {"error": f"'{report_name}' no tiene estructura PBIP."}

    term_lower = term.lower()
    model = pbi.parse_semantic_model(project.semantic_model_dir)
    model_matches = []
    for t in model["tables"]:
        for c in t["columns"]:
            if term_lower in c["name"].lower():
                model_matches.append({"type": "column", "table": t["name"], "name": c["name"]})
        for m in t["measures"]:
            if term_lower in m["name"].lower():
                model_matches.append({"type": "measure", "table": t["name"], "name": m["name"]})

    report = pbi.parse_report(project.report_dir)
    usage = []
    for pg in report["pages"]:
        for v in pg["visuals"]:
            for f in v["fields"]:
                if term_lower in (f["property"] or "").lower() or term_lower in (f["entity"] or "").lower():
                    usage.append(
                        {
                            "page": pg["displayName"],
                            "visual": v["title"] or v["visualType"],
                            "visualType": v["visualType"],
                            "field": f,
                        }
                    )

    return {"model_matches": model_matches, "visual_usage": usage}


if __name__ == "__main__":
    mcp.run()
