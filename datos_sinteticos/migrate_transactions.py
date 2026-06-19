#!/usr/bin/env python3
# Forzar locale C antes de importar psycopg2 para evitar UnicodeDecodeError
# con mensajes de error de PostgreSQL en Windows con locale español.
import os
os.environ.setdefault("LC_ALL", "C")
os.environ.setdefault("LC_MESSAGES", "C")
os.environ.setdefault("PGPASSFILE", "NUL")

"""
migrate_transactions.py
=======================
Pasos que ejecuta:
  1. Crea schema 'transacciones' y tabla unificada con year_month GENERADA.
  2. Migra registros existentes de produccion.transacciones (si los hay).
  3. Actualiza FK de produccion.fraude al nuevo schema.
  4. Elimina produccion.transacciones y todas sus particiones anuales.
  5. Genera 100 000 registros sintéticos con distribución progresiva 2010-2024.

Uso:
    python migrate_transactions.py [--seed N] [--skip-migrate]
"""

import argparse
import math
import random
import sys
import uuid
from datetime import datetime, timedelta

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(__file__))
from config import db_config, setup_logging

logger = setup_logging("migrate_transactions")

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────
SEED        = 42
FRAUD_RATE  = 0.025
N_TARGET    = 100_000
YEAR_START  = 2010
YEAR_END    = 2024

MCC_DATA = [
    (5411, "Supermercados",             "Retail",                 15),
    (5812, "Restaurantes",              "Gastronomia",            12),
    (5912, "Farmacias",                 "Salud",                   5),
    (5541, "Gasolineras",               "Combustible",             8),
    (5311, "Tiendas por departamento",  "Retail",                  6),
    (6011, "Cajero ATM",                "Servicios Financieros",   4),
    (6012, "Instituciones Financieras", "Servicios Financieros",   3),
    (5734, "Tecnologia",                "Tecnologia",              4),
    (7011, "Hoteles",                   "Viajes y Hospedaje",      3),
    (4111, "Transporte urbano",         "Transporte",              5),
    (4121, "Taxis y rideshare",         "Transporte",              4),
    (5621, "Ropa Mujer",                "Moda",                    2),
    (5651, "Ropa Familia",              "Moda",                    3),
    (5661, "Zapaterias",                "Moda",                    2),
    (5999, "Miscelaneo Retail",         "Retail",                  6),
    (4814, "Telefonia",                 "Telecomunicaciones",      3),
    (5045, "Electronica",               "Tecnologia",              2),
    (7832, "Entretenimiento",           "Entretenimiento",         2),
    (8011, "Medicos",                   "Salud",                   2),
    (5200, "Ferreterias",               "Construccion",            1),
]
MCC_CODES   = [m[0] for m in MCC_DATA]
MCC_CAT     = {m[0]: m[1] for m in MCC_DATA}
MCC_WEIGHTS = [m[3] for m in MCC_DATA]


# ──────────────────────────────────────────────────────────────────────────────
# DDL
# ──────────────────────────────────────────────────────────────────────────────
DDL_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS transacciones;
COMMENT ON SCHEMA transacciones IS
    'Dominio de transacciones financieras. '
    'Reemplaza las tablas particionadas anuales de produccion.';
"""

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS transacciones.transacciones (
    transaccion_id          UUID            NOT NULL DEFAULT gen_random_uuid(),
    transaction_id_origen   BIGINT,
    year_month              VARCHAR(7)      NOT NULL,
    usuario_origen_id       UUID            NOT NULL,
    usuario_destino_id      UUID,
    merchant_id             UUID,
    tarjeta_id              UUID,
    fecha_transaccion       TIMESTAMPTZ     NOT NULL,
    tipo_transaccion        VARCHAR(50)     NOT NULL,
    subtipo_transaccion     VARCHAR(100),
    monto                   NUMERIC(15,2)   NOT NULL,
    moneda                  CHAR(3)         NOT NULL DEFAULT 'USD',
    canal                   VARCHAR(30),
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'completada',
    costo_operativo         NUMERIC(12,4)   NOT NULL DEFAULT 0,
    ingreso_comision        NUMERIC(12,4)   NOT NULL DEFAULT 0,
    margen                  NUMERIC(12,4)   GENERATED ALWAYS AS
                                (ingreso_comision - costo_operativo) STORED,
    riesgo_score            NUMERIC(6,4),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_transacciones
        PRIMARY KEY (transaccion_id),
    CONSTRAINT fk_tx_usuario_origen
        FOREIGN KEY (usuario_origen_id)
        REFERENCES produccion.usuarios (usuario_id) ON DELETE RESTRICT,
    CONSTRAINT fk_tx_usuario_destino
        FOREIGN KEY (usuario_destino_id)
        REFERENCES produccion.usuarios (usuario_id) ON DELETE RESTRICT,
    CONSTRAINT fk_tx_merchant
        FOREIGN KEY (merchant_id)
        REFERENCES produccion.merchants (merchant_id) ON DELETE SET NULL,
    CONSTRAINT fk_tx_tarjeta
        FOREIGN KEY (tarjeta_id)
        REFERENCES produccion.tarjetas (tarjeta_id) ON DELETE SET NULL,
    CONSTRAINT ck_tx_monto      CHECK (monto <> 0),
    CONSTRAINT ck_tx_estado     CHECK (estado IN
        ('completada','pendiente','rechazada','revertida','error')),
    CONSTRAINT ck_tx_canal      CHECK (canal IN
        ('chip','banda_magnetica','online','nfc','atm','transferencia','otro') OR canal IS NULL),
    CONSTRAINT ck_tx_tipo       CHECK (tipo_transaccion IN
        ('compra','retiro','transferencia','pago_servicio','recarga','devolucion','ajuste','otro')),
    CONSTRAINT ck_tx_costo      CHECK (costo_operativo >= 0),
    CONSTRAINT ck_tx_comision   CHECK (ingreso_comision >= 0),
    CONSTRAINT ck_tx_riesgo     CHECK (riesgo_score IS NULL OR riesgo_score BETWEEN 0 AND 1)
);

COMMENT ON TABLE  transacciones.transacciones IS
    'Tabla central de transacciones. year_month y margen son columnas generadas.';

CREATE INDEX IF NOT EXISTS idx_tx_year_month  ON transacciones.transacciones (year_month);
CREATE INDEX IF NOT EXISTS idx_tx_fecha_desc  ON transacciones.transacciones (fecha_transaccion DESC);
CREATE INDEX IF NOT EXISTS idx_tx_usuario     ON transacciones.transacciones (usuario_origen_id);
CREATE INDEX IF NOT EXISTS idx_tx_merchant    ON transacciones.transacciones (merchant_id);
CREATE INDEX IF NOT EXISTS idx_tx_tarjeta     ON transacciones.transacciones (tarjeta_id);
CREATE INDEX IF NOT EXISTS idx_tx_estado      ON transacciones.transacciones (estado);
CREATE INDEX IF NOT EXISTS idx_tx_tipo        ON transacciones.transacciones (tipo_transaccion);
CREATE INDEX IF NOT EXISTS idx_tx_monto       ON transacciones.transacciones (monto);
CREATE INDEX IF NOT EXISTS idx_tx_riesgo_alto ON transacciones.transacciones (riesgo_score DESC)
    WHERE riesgo_score > 0.5;
"""

# year_month es columna regular → se incluye en INSERT; margen es GENERATED → se excluye
TX_COLS = [
    "transaccion_id", "transaction_id_origen", "year_month",
    "usuario_origen_id", "usuario_destino_id", "merchant_id", "tarjeta_id",
    "fecha_transaccion", "tipo_transaccion", "subtipo_transaccion",
    "monto", "moneda", "canal", "estado",
    "costo_operativo", "ingreso_comision", "riesgo_score",
]

# La tabla vieja no tiene year_month → se computa en el SELECT
_MIGRATE_OLD_COLS = [c for c in TX_COLS if c != "year_month"]
SQL_MIGRATE = f"""
INSERT INTO transacciones.transacciones ({', '.join(TX_COLS)})
SELECT
    transaccion_id,
    transaction_id_origen,
    TO_CHAR(fecha_transaccion AT TIME ZONE 'UTC', 'YYYY-MM') AS year_month,
    {', '.join(_MIGRATE_OLD_COLS[2:])}
FROM produccion.transacciones
ON CONFLICT (transaccion_id) DO NOTHING;
"""

SQL_UPDATE_FRAUDE_FK = """
ALTER TABLE produccion.fraude
    DROP CONSTRAINT IF EXISTS fk_fraude_transaccion;

ALTER TABLE produccion.fraude
    ADD CONSTRAINT fk_fraude_transaccion
    FOREIGN KEY (transaccion_id)
    REFERENCES transacciones.transacciones (transaccion_id)
    ON DELETE CASCADE;
"""

SQL_DROP_OLD = """
DROP TABLE IF EXISTS produccion.transacciones CASCADE;
"""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def wchoice(choices, weights):
    return random.choices(choices, weights=weights, k=1)[0]


def new_uuid():
    return str(uuid.uuid4())


def rand_dt_in_year(year: int) -> datetime:
    start = datetime(year, 1, 1)
    end   = datetime(year, 12, 31, 23, 59, 59)
    return start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))


def progressive_distribution(year_start: int, year_end: int, total: int) -> dict[int, int]:
    """
    Peso proporcional a (year - year_start + 1):
    el año más antiguo recibe la menor cantidad,
    el más reciente la mayor → crecimiento lineal.
    """
    years   = list(range(year_start, year_end + 1))
    weights = [y - year_start + 1 for y in years]
    total_w = sum(weights)
    dist = {}
    allocated = 0
    for y, w in zip(years[:-1], weights[:-1]):
        n = round(total * w / total_w)
        dist[y] = n
        allocated += n
    dist[years[-1]] = total - allocated
    return dist


# ──────────────────────────────────────────────────────────────────────────────
# Generación de 100k registros
# ──────────────────────────────────────────────────────────────────────────────
def generate_100k(cur) -> None:
    logger.info("Cargando entidades de referencia (usuarios, merchants, tarjetas)...")
    cur.execute("SELECT usuario_id FROM produccion.usuarios")
    usuarios = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT merchant_id, mcc_code FROM produccion.merchants")
    merchants     = {r[0]: r[1] for r in cur.fetchall()}
    merchant_ids  = list(merchants.keys())

    cur.execute("SELECT tarjeta_id, usuario_id FROM produccion.tarjetas")
    cards_by_user: dict[str, list] = {}
    for tid, uid in cur.fetchall():
        cards_by_user.setdefault(uid, []).append(tid)

    if not usuarios:
        raise RuntimeError(
            "No hay usuarios en produccion.usuarios. "
            "Ejecuta generate_synthetic_data.py primero."
        )

    canales   = ["chip", "banda_magnetica", "online", "nfc", "atm", "transferencia", "otro"]
    canal_w   = [35, 20, 25, 10, 5, 4, 1]
    estados   = ["completada", "pendiente", "rechazada", "revertida", "error"]
    estado_w  = [88, 5, 4, 2, 1]
    tipo_tx   = ["compra", "transferencia", "pago_servicio", "recarga"]
    tipo_tx_w = [75, 10, 10, 5]

    dist = progressive_distribution(YEAR_START, YEAR_END, N_TARGET)
    logger.info("Distribución por año (progresiva, lineal):")
    for y, n in dist.items():
        logger.info("  %d → %d registros", y, n)

    tx_offset     = 900_000   # evita colisión con transaction_id_origen anteriores
    total_gen     = 0
    PAGE_SIZE     = 5_000

    for year, count in dist.items():
        batch = []
        for i in range(count):
            uid = random.choice(usuarios)
            mid = random.choice(merchant_ids)
            mcc = merchants[mid]

            tipo = ("retiro" if mcc in (6011, 6012)
                    else wchoice(tipo_tx, tipo_tx_w))

            monto = (float(random.choice([20, 40, 60, 80, 100, 200, 300, 500]))
                     if tipo == "retiro"
                     else round(max(0.01, float(np.random.lognormal(3.5, 1.2))), 2))

            is_fraud  = random.random() < FRAUD_RATE
            riesgo    = (round(random.uniform(0.70, 0.99), 4) if is_fraud
                         else round(random.uniform(0.01, 0.15), 4))

            fecha_tx   = rand_dt_in_year(year)
            monto_abs  = abs(monto)
            tarjeta_id = (random.choice(cards_by_user[uid])
                          if uid in cards_by_user and random.random() > 0.10 else None)

            batch.append((
                new_uuid(),                              # transaccion_id
                tx_offset + total_gen + i,               # transaction_id_origen
                fecha_tx.strftime("%Y-%m"),              # year_month
                uid,                                     # usuario_origen_id
                None,                                    # usuario_destino_id
                mid,                                     # merchant_id
                tarjeta_id,                              # tarjeta_id
                fecha_tx,                                # fecha_transaccion
                tipo,                                    # tipo_transaccion
                MCC_CAT.get(mcc, "Otro"),                # subtipo_transaccion
                monto,                                   # monto
                "USD",                                   # moneda
                wchoice(canales, canal_w),               # canal
                wchoice(estados, estado_w),              # estado
                round(monto_abs * 0.008, 4),             # costo_operativo
                round(monto_abs * 0.018, 4),             # ingreso_comision
                riesgo,                                  # riesgo_score
            ))

        sql = (
            f"INSERT INTO transacciones.transacciones ({', '.join(TX_COLS)}) "
            "VALUES %s ON CONFLICT DO NOTHING"
        )
        execute_values(cur, sql, batch, page_size=PAGE_SIZE)
        total_gen += count
        logger.info("  Año %d: %d registros insertados (total: %d)", year, count, total_gen)

    logger.info("Generación completada: %d registros.", total_gen)


# ──────────────────────────────────────────────────────────────────────────────
# Conexión
# ──────────────────────────────────────────────────────────────────────────────
def get_conn():
    try:
        return psycopg2.connect(
            host=db_config.host,
            port=db_config.port,
            dbname=db_config.database,
            user=db_config.user,
            password=db_config.password,
        )
    except UnicodeDecodeError as e:
        raise RuntimeError(
            f"psycopg2 no pudo decodificar el mensaje de error de PostgreSQL "
            f"(Windows locale español). "
            f"Verifica la contraseña en .env: "
            f"host={db_config.host} db={db_config.database} user={db_config.user}"
        ) from e


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migra transacciones a nuevo schema y genera 100k registros"
    )
    parser.add_argument("--seed",         type=int, default=SEED)
    parser.add_argument("--skip-migrate", action="store_true",
                        help="Omitir migración de datos existentes (solo crear schema + 100k)")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    logger.info("=== Migración a schema transacciones + generación de 100k ===")

    conn = get_conn()
    conn.autocommit = False
    cur  = conn.cursor()

    try:
        # ── Paso 1: crear schema y tabla ────────────────────────────────────
        logger.info("[1/5] Creando schema transacciones y tabla unificada...")
        cur.execute(DDL_SCHEMA)
        cur.execute(DDL_TABLE)
        logger.info("  Schema y tabla creados.")

        # ── Paso 2: migrar datos existentes ─────────────────────────────────
        if not args.skip_migrate:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'produccion'
                      AND table_name   = 'transacciones'
                )
            """)
            old_exists = cur.fetchone()[0]

            if old_exists:
                cur.execute("SELECT COUNT(*) FROM produccion.transacciones")
                n_old = cur.fetchone()[0]
                if n_old > 0:
                    logger.info("[2/5] Migrando %d registros de produccion.transacciones...", n_old)
                    cur.execute(SQL_MIGRATE)
                    logger.info("  Migración completada.")
                else:
                    logger.info("[2/5] produccion.transacciones existe pero está vacía.")
            else:
                logger.info("[2/5] produccion.transacciones no existe, no hay datos que migrar.")
        else:
            logger.info("[2/5] Migración omitida (--skip-migrate).")

        # ── Paso 3: actualizar FK de fraude ──────────────────────────────────
        logger.info("[3/5] Actualizando FK de produccion.fraude → transacciones.transacciones...")
        cur.execute(SQL_UPDATE_FRAUDE_FK)
        logger.info("  FK actualizada.")

        # ── Paso 4: eliminar tabla particionada antigua ───────────────────────
        logger.info("[4/5] Eliminando produccion.transacciones y particiones anuales...")
        cur.execute(SQL_DROP_OLD)
        logger.info("  Tabla antigua eliminada (incluye transacciones_2010 … transacciones_default).")

        # ── Paso 5: generar 100k registros ───────────────────────────────────
        logger.info("[5/5] Generando 100,000 registros progresivos %d-%d...",
                    YEAR_START, YEAR_END)
        generate_100k(cur)

        conn.commit()
        logger.info("=== Proceso completado exitosamente ===")

        # Resumen
        cur.execute("SELECT COUNT(*) FROM transacciones.transacciones")
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT year_month, COUNT(*)
            FROM transacciones.transacciones
            GROUP BY year_month
            ORDER BY year_month
        """)
        logger.info("Total registros en transacciones.transacciones: %d", total)
        logger.info("Distribución final por mes:")
        for ym, cnt in cur.fetchall():
            logger.info("  %s : %d", ym, cnt)

    except Exception:
        conn.rollback()
        logger.exception("Error durante el proceso — rollback ejecutado.")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
