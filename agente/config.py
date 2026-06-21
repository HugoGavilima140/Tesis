"""
agente/config.py — Configuración del Business Reasoning Agent para PayNova.

Variables de entorno requeridas (.env):
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD, PG_SCHEMA
    OPENAI_KEY, LLM_MODEL, LLM_BASE_URL
    KB_DIR  (opcional: ruta custom a la base de conocimiento Markdown)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Rutas ────────────────────────────────────────────────────────────────────
AGENT_DIR   = Path(__file__).parent
PROJECT_DIR = AGENT_DIR.parent

_KB_ENV = os.getenv("KB_DIR", "")
KB_DIR = Path(_KB_ENV) if _KB_ENV else PROJECT_DIR / "knowledge_base"

MEMORY_PATH  = AGENT_DIR / "memory_store.json"
KB_INDEX_DIR = AGENT_DIR / "kb_embeddings"
KB_INDEX_DIR.mkdir(parents=True, exist_ok=True)

# ─── PostgreSQL ───────────────────────────────────────────────────────────────
PG_HOST     = os.environ["PG_HOST"]
PG_PORT     = int(os.environ["PG_PORT"])
PG_DATABASE = os.environ["PG_DATABASE"]
PG_USER     = os.environ["PG_USER"]
PG_PASSWORD = os.environ["PG_PASSWORD"]
PG_SCHEMA   = os.environ["PG_SCHEMA"]

PG_URL = (
    f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}"
    f"@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
)

# ─── LLM ─────────────────────────────────────────────────────────────────────
LLM_API_KEY     = os.environ["OPENAI_KEY"]
LLM_MODEL       = os.environ["LLM_MODEL"]
LLM_BASE_URL    = os.environ["LLM_BASE_URL"]
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS  = 2048
LLM_TIMEOUT     = 180
LLM_MAX_RETRIES = 3

# ─── Embeddings ───────────────────────────────────────────────────────────────
EMBED_MODEL    = "all-MiniLM-L6-v2"
EMBED_DIM      = 384
KB_CHUNK_SIZE  = 800    # chars por chunk de markdown
KB_CHUNK_OVERLAP = 100
TOP_K_KB       = 5      # chunks de KB a recuperar por pregunta
TOP_K_TABLES   = 8      # tablas candidatas máximas

# ─── ReAct Loop ───────────────────────────────────────────────────────────────
MAX_REACT_ITERATIONS = 6   # iteraciones máximas del loop Think-Act-Observe
MAX_SQL_STEPS        = 5   # subqueries máximas por plan
MAX_RETRIES_SQL      = 3   # reintentos de corrección SQL
MAX_TABLE_RETRIES    = 2   # Mod 4: reintentos de selección de tablas por paso
MAX_CRITIC_ITERS     = 2   # Mod 6/7: iteraciones máximas del critic agent

# ─── Confidence Score ─────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLDS = {
    "respond_normal":    85,
    "respond_limited":   70,
    "request_partial":   50,
    "request_clarification": 0,
}

# ─── Esquema PayNova (catálogo de tablas) ─────────────────────────────────────
PAYNOVA_TABLES = {
    "produccion.usuarios": {
        "description": "Usuarios/clientes de la plataforma PayNova",
        "key_columns": ["usuario_id", "estado", "nivel_riesgo", "score_actividad", "score_rentabilidad"],
        "domains": ["usuarios", "segmentacion", "riesgo"],
    },
    "produccion.merchants": {
        "description": "Comercios afiliados a la plataforma",
        "key_columns": ["merchant_id", "merchant_name", "mcc", "mcc_categoria", "status_operacional", "coordinador_id"],
        "domains": ["comercios", "operaciones", "finanzas"],
    },
    "produccion.segmentacion_merchants": {
        "description": "Segmentación por volumen y rentabilidad de comercios",
        "key_columns": ["merchant_id", "segmento_volumen", "segmento_rentabilidad", "estado_riesgo", "mdr_promedio"],
        "domains": ["comercios", "segmentacion", "estrategia"],
    },
    "produccion.account_managers": {
        "description": "Gestores comerciales y sus portafolios",
        "key_columns": ["manager_id", "nombre", "email", "region", "estado"],
        "domains": ["comercios", "operaciones"],
    },
    "produccion.integraciones_merchant": {
        "description": "Estado del onboarding e integración técnica de comercios",
        "key_columns": ["merchant_id", "estado_integracion", "api_key_validado", "email_integrado", "sms_integrado"],
        "domains": ["comercios", "operaciones", "funnel"],
    },
    "produccion.payouts": {
        "description": "Liquidaciones/desembolsos a comercios",
        "key_columns": ["merchant_id", "monto", "comision_payout", "monto_neto", "estado", "fecha_payout"],
        "domains": ["finanzas", "operaciones"],
    },
    "produccion.notificaciones": {
        "description": "Comunicaciones enviadas a comercios (email, SMS, push, etc.)",
        "key_columns": ["merchant_id", "tipo_canal", "cantidad_enviada", "costo_total", "estado", "tasa_apertura"],
        "domains": ["marketing", "finanzas"],
    },
    "produccion.fraude": {
        "description": "Alertas de fraude detectadas por el sistema",
        "key_columns": ["transaccion_id", "flag_fraude", "riesgo_score", "tipo_alerta", "estado_revision"],
        "domains": ["riesgo", "fraude"],
    },
    "produccion.segmentacion": {
        "description": "Segmentación de usuarios por actividad y rentabilidad",
        "key_columns": ["usuario_id", "segmento_transaccional", "segmento_rentabilidad", "cluster_ml"],
        "domains": ["usuarios", "segmentacion"],
    },
    "transacciones.transacciones": {
        "description": "Tabla central de transacciones financieras (24M+ registros)",
        "key_columns": [
            "transaccion_id", "merchant_id", "usuario_origen_id", "monto",
            "ingreso_comision", "costo_operativo", "margen", "estado",
            "canal_pago", "tipo_transaccion", "riesgo_score", "flag_fraude",
            "fecha_transaccion", "year_month", "hora_transaccion"
        ],
        "domains": ["finanzas", "transacciones", "riesgo", "fraude"],
    },
    "produccion.vw_funnel_comercios": {
        "description": "Vista del funnel de onboarding de comercios",
        "key_columns": ["etapa", "cantidad", "conversion_pct"],
        "domains": ["comercios", "operaciones", "funnel"],
        "is_view": True,
    },
    "produccion.mv_metricas_diarias": {
        "description": "Vista materializada de KPIs diarios por comercio",
        "key_columns": ["merchant_id", "fecha", "gmv", "ingresos_mdr", "margen_bruto", "total_transacciones"],
        "domains": ["finanzas", "comercios"],
        "is_view": True,
    },
    "produccion.vw_kpi_dashboard": {
        "description": "Vista de KPIs ejecutivos del dashboard",
        "key_columns": ["metrica", "valor", "periodo"],
        "domains": ["finanzas", "ejecutivo"],
        "is_view": True,
    },
}

PAYNOVA_BUSINESS_RULES = """
REGLAS DE NEGOCIO CRÍTICAS:
- MDR estándar = 1.8% del monto (ingreso_comision = monto * 0.018)
- Costo operativo = 0.8% del monto (costo_operativo = monto * 0.008)
- Margen = MDR - Costo = 1.0% del monto (GENERATED ALWAYS AS)
- monto_neto en payouts = monto - comision_payout (GENERATED ALWAYS AS)
- costo_total en notificaciones = cantidad_enviada * costo_unitario (GENERATED ALWAYS AS)
- NUNCA usar SUM(monto) como ingresos de PayNova; usar SUM(ingreso_comision)
- Usuario activo = ha transaccionado en los últimos 30 días (NO es usuarios.estado='activo')
- Comercio activo = merchants.status_operacional='activo' AND ultima_actividad >= hoy-30
- Para filtrar por mes usar year_month = 'YYYY-MM' (más eficiente que DATE_TRUNC)
- Solo contar transacciones con estado='completada' para métricas de negocio
- Tasa de fraude objetivo < 0.5% (la del dataset IBM ~2.5% es sintética elevada)
"""
