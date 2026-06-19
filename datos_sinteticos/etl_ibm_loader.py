"""
ETL principal: IBM Financial Transaction Dataset → PostgreSQL produccion

Flujo de carga:
  1. Leer CSV IBM
  2. Preprocesar columnas
  3. Cargar tablas en orden de dependencia FK:
     merchants → usuarios → tarjetas → transacciones → fraude
     → usuarios_demographics → segmentacion → dispositivos → aplicacion
  4. Actualizar etl_control
"""
from __future__ import annotations

import math
import random
import uuid
from datetime import date, datetime
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import DBConfig, db_config, setup_logging
from utils import (
    calc_costo_operativo, calc_ingreso_comision,
    gen_canal_adquisicion, gen_device_type, gen_engagement_score,
    gen_fraud_tipo, gen_genero, gen_limite_credito, gen_nivel_ingreso,
    gen_ocupacion, gen_os, gen_rango_edad, gen_tarjeta_marca,
    is_fraud, map_canal, map_estado, mcc_to_category,
    mcc_to_segment, mcc_to_tipo_tx, nivel_riesgo_from_pct,
    parse_amount, parse_ibm_datetime, riesgo_score_from_fraud,
    score_actividad, score_rentabilidad, segmento_rentabilidad_label,
    segmento_transaccional, gen_app_version,
)

log = setup_logging("ETL_IBM")


# ──────────────────────────────────────────────────────────────
class IBMDatasetETL:
    """
    Carga completa del IBM Financial Transaction Dataset.

    Parámetros
    ----------
    csv_path   : ruta al archivo CSV del dataset IBM
    batch_size : registros por batch al insertar transacciones
    config     : instancia DBConfig (usa db_config global por defecto)
    """

    def __init__(
        self,
        csv_path: str,
        batch_size: int = 10_000,
        config: DBConfig = db_config,
    ) -> None:
        self.csv_path   = csv_path
        self.batch_size = batch_size
        self.engine: Engine = create_engine(
            config.url,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow,
            pool_pre_ping=True,
        )

    # ──────────────────────────────────────────────────
    # 1. CARGA Y PREPROCESAMIENTO
    # ──────────────────────────────────────────────────
    def load_and_preprocess(self) -> pd.DataFrame:
        log.info(f"Leyendo CSV: {self.csv_path}")
        df = pd.read_csv(self.csv_path, low_memory=False)
        log.info(f"Filas leídas: {len(df):,}  |  Columnas: {list(df.columns)}")

        # Columnas numéricas IBM requeridas
        for col in ["User", "Card", "Year", "Month", "Day", "MCC"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        df["monto"]             = df["Amount"].apply(parse_amount)
        df["fecha_transaccion"] = df.apply(parse_ibm_datetime, axis=1)
        df["canal"]             = df["Use Chip"].apply(map_canal)
        df["estado_tx"]         = df["Errors?"].apply(map_estado)
        df["flag_fraude"]       = df["Is Fraud?"].apply(is_fraud)
        df["riesgo_score"]      = df["flag_fraude"].apply(riesgo_score_from_fraud)
        df["costo_operativo"]   = df["monto"].apply(calc_costo_operativo)
        df["ingreso_comision"]  = df["monto"].apply(calc_ingreso_comision)
        df["tipo_transaccion"]  = df["MCC"].apply(mcc_to_tipo_tx)
        df["subtipo_tx"]        = df["MCC"].apply(mcc_to_category)

        log.info(f"Fraudes en dataset: {df['flag_fraude'].sum():,} "
                 f"({df['flag_fraude'].mean()*100:.2f}%)")
        return df

    # ──────────────────────────────────────────────────
    # 2. MERCHANTS
    # ──────────────────────────────────────────────────
    def load_merchants(self, df: pd.DataFrame) -> Dict[int, str]:
        """Retorna {merchant_id_origen: merchant_uuid}"""
        log.info("Cargando merchants...")

        mdf = (
            df[["Merchant Name", "Merchant City", "Merchant State", "Zip", "MCC"]]
            .drop_duplicates(subset=["Merchant Name"])
            .copy()
        )
        mdf.columns = ["merchant_id_origen", "ciudad", "estado_region", "zip_code", "mcc_code"]
        mdf["merchant_id"]    = [str(uuid.uuid4()) for _ in range(len(mdf))]
        mdf["nombre_comercio"]= mdf["merchant_id_origen"].astype(str)
        mdf["categoria"]      = mdf["mcc_code"].apply(mcc_to_category)
        mdf["segmento"]       = mdf["mcc_code"].apply(mcc_to_segment)
        mdf["pais"]           = "USA"
        mdf["fecha_afiliacion"] = date(2018, 1, 1)
        mdf["estado"]         = "activo"

        cols = [
            "merchant_id", "merchant_id_origen", "nombre_comercio",
            "categoria", "mcc_code", "segmento", "ciudad",
            "estado_region", "zip_code", "pais", "fecha_afiliacion", "estado",
        ]
        self._bulk_insert(mdf[cols], "merchants")
        log.info(f"Merchants insertados: {len(mdf):,}")
        return self._fetch_map("SELECT merchant_id_origen, merchant_id FROM produccion.merchants")

    # ──────────────────────────────────────────────────
    # 3. USUARIOS
    # ──────────────────────────────────────────────────
    def load_usuarios(self, df: pd.DataFrame) -> Dict[int, str]:
        """Retorna {customer_id_origen: usuario_uuid}"""
        log.info("Cargando usuarios...")

        agg = df.groupby("User").agg(
            fecha_registro    = ("fecha_transaccion", "min"),
            n_tx              = ("monto", "count"),
            monto_total       = ("monto", lambda x: x.abs().sum()),
            pct_fraude        = ("flag_fraude", "mean"),
            ciudad            = ("Merchant City", lambda x: x.mode().iloc[0] if len(x) > 0 else None),
        ).reset_index()
        agg.rename(columns={"User": "customer_id_origen"}, inplace=True)

        max_log   = math.log1p(agg["n_tx"].max())
        max_monto = agg["monto_total"].max()

        agg["usuario_id"]          = [str(uuid.uuid4()) for _ in range(len(agg))]
        agg["fecha_registro"]      = agg["fecha_registro"].dt.date
        agg["estado"]              = "activo"
        agg["tipo_usuario"]        = "individual"
        agg["pais"]                = "USA"
        agg["nivel_riesgo"]        = agg["pct_fraude"].apply(nivel_riesgo_from_pct)
        agg["score_actividad"]     = agg["n_tx"].apply(
            lambda n: score_actividad(n, max_log)
        )
        agg["score_rentabilidad"]  = agg["monto_total"].apply(
            lambda m: score_rentabilidad(m, max_monto)
        )

        cols = [
            "usuario_id", "customer_id_origen", "fecha_registro",
            "estado", "tipo_usuario", "nivel_riesgo",
            "pais", "ciudad", "score_actividad", "score_rentabilidad",
        ]
        self._bulk_insert(agg[cols], "usuarios")
        log.info(f"Usuarios insertados: {len(agg):,}")
        return self._fetch_map("SELECT customer_id_origen, usuario_id FROM produccion.usuarios")

    # ──────────────────────────────────────────────────
    # 4. TARJETAS
    # ──────────────────────────────────────────────────
    def load_tarjetas(
        self, df: pd.DataFrame, usuario_map: Dict[int, str]
    ) -> Dict[Tuple[int, int], str]:
        """Retorna {(card_id_origen, customer_id_origen): tarjeta_uuid}"""
        log.info("Cargando tarjetas...")

        tdf = (
            df.groupby(["Card", "User"])
            .agg(
                tipo_uso     = ("Use Chip", lambda x: x.mode().iloc[0]),
                fecha_emision= ("fecha_transaccion", "min"),
                n_tx         = ("monto", "count"),
            )
            .reset_index()
        )
        tdf["tarjeta_id"]     = [str(uuid.uuid4()) for _ in range(len(tdf))]
        tdf["usuario_id"]     = tdf["User"].map(usuario_map)
        tdf["card_id_origen"] = tdf["Card"]
        tdf["fecha_emision"]  = tdf["fecha_emision"].dt.date
        tdf["tipo_tarjeta"]   = tdf["tipo_uso"].map({
            "Chip Transaction":   "debito",
            "Swipe Transaction":  "debito",
            "Online Transaction": "virtual",
        }).fillna("debito")
        tdf["marca"]          = [gen_tarjeta_marca() for _ in range(len(tdf))]
        tdf["estado"]         = "activa"
        tdf["score_uso"]      = np.clip(
            np.random.normal(60, 20, len(tdf)), 5, 99
        ).round(2)
        tdf["limite_credito"] = tdf["tipo_tarjeta"].apply(gen_limite_credito)

        cols = [
            "tarjeta_id", "card_id_origen", "usuario_id",
            "tipo_tarjeta", "marca", "estado",
            "fecha_emision", "limite_credito", "score_uso",
        ]
        self._bulk_insert(tdf[cols], "tarjetas")
        log.info(f"Tarjetas insertadas: {len(tdf):,}")

        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT card_id_origen, usuario_id, tarjeta_id FROM produccion.tarjetas"
            ))
            uid_map = {u: cid for u, cid in
                       self._fetch_map("SELECT usuario_id, customer_id_origen FROM produccion.usuarios",
                                       reverse=True).items()}
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT card_id_origen, usuario_id, tarjeta_id FROM produccion.tarjetas"
            ))
            # Build (card_id_origen, usuario_id) → tarjeta_id
            # We need (card_id_origen, customer_id_origen) → tarjeta_id
            usr_to_cust = self._fetch_map(
                "SELECT usuario_id, customer_id_origen FROM produccion.usuarios"
            )
            return {
                (row[0], usr_to_cust.get(row[1], -1)): row[2]
                for row in rows
            }

    # ──────────────────────────────────────────────────
    # 5. TRANSACCIONES
    # ──────────────────────────────────────────────────
    def load_transacciones(
        self,
        df: pd.DataFrame,
        usuario_map: Dict[int, str],
        merchant_map: Dict[int, str],
        tarjeta_map: Dict[Tuple[int, int], str],
    ) -> None:
        log.info(f"Cargando {len(df):,} transacciones en batches de {self.batch_size:,}...")

        n_batches = math.ceil(len(df) / self.batch_size)
        for i, start in enumerate(range(0, len(df), self.batch_size)):
            chunk = df.iloc[start: start + self.batch_size].copy()

            chunk["transaccion_id"]       = [str(uuid.uuid4()) for _ in range(len(chunk))]
            chunk["transaction_id_origen"]= chunk.index
            chunk["usuario_origen_id"]    = chunk["User"].map(usuario_map)
            chunk["merchant_id"]          = chunk["Merchant Name"].map(merchant_map)
            chunk["tarjeta_id"]           = chunk.apply(
                lambda r: tarjeta_map.get((r["Card"], r["User"])), axis=1
            )
            chunk["moneda"] = "USD"

            tx_cols = [
                "transaccion_id", "transaction_id_origen",
                "usuario_origen_id", "merchant_id", "tarjeta_id",
                "fecha_transaccion", "tipo_transaccion", "subtipo_tx",
                "monto", "moneda", "canal", "estado_tx",
                "costo_operativo", "ingreso_comision", "riesgo_score",
            ]
            out = chunk[tx_cols].rename(columns={
                "subtipo_tx": "subtipo_transaccion",
                "estado_tx":  "estado",
            })
            self._bulk_insert(out, "transacciones")
            log.info(f"  Batch {i+1}/{n_batches} ({start + len(chunk):,} filas acumuladas)")

    # ──────────────────────────────────────────────────
    # 6. FRAUDE
    # ──────────────────────────────────────────────────
    def load_fraude(self, df: pd.DataFrame) -> None:
        fraud_df = df[df["flag_fraude"]].copy()
        log.info(f"Registros de fraude: {len(fraud_df):,}")
        if fraud_df.empty:
            return

        tx_map = self._fetch_map(
            "SELECT transaction_id_origen, transaccion_id FROM produccion.transacciones"
        )
        date_map = self._fetch_map(
            "SELECT transaction_id_origen, fecha_transaccion FROM produccion.transacciones",
            cast_key=int,
        )

        fraud_df["transaccion_id"]   = fraud_df.index.map(tx_map)
        fraud_df["fecha_transaccion_fk"] = fraud_df.index.map(date_map)
        fraud_df = fraud_df[fraud_df["transaccion_id"].notna()]

        fraud_df["fraude_id"]       = [str(uuid.uuid4()) for _ in range(len(fraud_df))]
        fraud_df["tipo_alerta"]     = [gen_fraud_tipo() for _ in range(len(fraud_df))]
        fraud_df["score_fraude"]    = np.random.uniform(0.70, 0.99, len(fraud_df)).round(4)
        fraud_df["modelo_detector"] = "IBM_Label_v1"
        fraud_df["fecha_deteccion"] = fraud_df["fecha_transaccion"]
        fraud_df["estado_revision"] = "confirmado"

        cols = [
            "fraude_id", "transaccion_id", "fecha_transaccion_fk",
            "flag_fraude", "tipo_alerta", "score_fraude",
            "modelo_detector", "fecha_deteccion", "estado_revision",
        ]
        out = fraud_df[cols].rename(columns={"fecha_transaccion_fk": "fecha_transaccion"})
        self._bulk_insert(out, "fraude")
        log.info("Fraude cargado.")

    # ──────────────────────────────────────────────────
    # 7. DEMOGRAPHICS (sintético)
    # ──────────────────────────────────────────────────
    def load_demographics(self, usuario_map: Dict[int, str]) -> None:
        log.info("Generando datos demográficos sintéticos...")
        rows = []
        for cust_id, usr_uuid in usuario_map.items():
            rows.append({
                "usuario_id":              usr_uuid,
                "rango_edad":              gen_rango_edad(),
                "genero":                  gen_genero(),
                "ocupacion":               gen_ocupacion(),
                "nivel_ingresos_estimado": gen_nivel_ingreso(),
                "antiguedad_cliente":      random.randint(0, 10),
            })
        demo_df = pd.DataFrame(rows)
        self._bulk_insert(demo_df, "usuarios_demographics")
        log.info(f"Demographics insertados: {len(demo_df):,}")

    # ──────────────────────────────────────────────────
    # 8. DISPOSITIVOS (sintético)
    # ──────────────────────────────────────────────────
    def load_dispositivos(self, df: pd.DataFrame, usuario_map: Dict[int, str]) -> None:
        log.info("Generando dispositivos sintéticos...")
        user_dates = df.groupby("User")["fecha_transaccion"].agg(["min", "max"])
        rows = []
        for cust_id, usr_uuid in usuario_map.items():
            n_devices = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
            dt_range = user_dates.loc[cust_id] if cust_id in user_dates.index else None
            for _ in range(n_devices):
                dev_type = gen_device_type()
                rows.append({
                    "dispositivo_id":    str(uuid.uuid4()),
                    "usuario_id":        usr_uuid,
                    "device_type":       dev_type,
                    "sistema_operativo": gen_os(dev_type),
                    "version_app":       gen_app_version(),
                    "fecha_primer_uso":  dt_range["min"].date() if dt_range is not None else None,
                    "fecha_ultimo_uso":  dt_range["max"].date() if dt_range is not None else None,
                    "estado_dispositivo": "activo",
                })
        dev_df = pd.DataFrame(rows)
        self._bulk_insert(dev_df, "dispositivos")
        log.info(f"Dispositivos insertados: {len(dev_df):,}")

    # ──────────────────────────────────────────────────
    # 9. APLICACIÓN (sintético)
    # ──────────────────────────────────────────────────
    def load_aplicacion(self, df: pd.DataFrame, usuario_map: Dict[int, str]) -> None:
        log.info("Generando registros de app sintéticos...")
        user_stats = df.groupby("User")["monto"].count().rename("n_tx")
        rows = []
        for cust_id, usr_uuid in usuario_map.items():
            n_tx = int(user_stats.get(cust_id, 5))
            rows.append({
                "app_id":            str(uuid.uuid4()),
                "usuario_id":        usr_uuid,
                "version":           gen_app_version(),
                "canal_adquisicion": gen_canal_adquisicion(),
                "fecha_activacion":  None,
                "estado":            "activa",
                "engagement_score":  gen_engagement_score(n_tx),
            })
        app_df = pd.DataFrame(rows)
        self._bulk_insert(app_df, "aplicacion")
        log.info(f"Registros app insertados: {len(app_df):,}")

    # ──────────────────────────────────────────────────
    # 10. SEGMENTACIÓN (calculada)
    # ──────────────────────────────────────────────────
    def load_segmentacion(self, df: pd.DataFrame, usuario_map: Dict[int, str]) -> None:
        log.info("Calculando segmentación de usuarios...")
        stats = df.groupby("User").agg(
            n_tx        = ("monto", "count"),
            score_rent  = ("monto", lambda x: x.abs().sum()),
            pct_fraude  = ("flag_fraude", "mean"),
        )
        max_rent  = stats["score_rent"].max()
        stats["score_rent_norm"] = (stats["score_rent"] / max_rent * 100).round(2)

        pcts = (
            stats["n_tx"].quantile(0.25),
            stats["n_tx"].quantile(0.50),
            stats["n_tx"].quantile(0.75),
        )

        rows = []
        for cust_id, usr_uuid in usuario_map.items():
            if cust_id not in stats.index:
                continue
            row = stats.loc[cust_id]
            rows.append({
                "segmentacion_id":       str(uuid.uuid4()),
                "usuario_id":            usr_uuid,
                "segmento_transaccional":segmento_transaccional(int(row["n_tx"]), pcts),
                "segmento_rentabilidad": segmento_rentabilidad_label(float(row["score_rent_norm"])),
                "segmento_riesgo":       nivel_riesgo_from_pct(float(row["pct_fraude"])),
                "cluster_ml":            None,
                "fecha_segmentacion":    date.today(),
            })
        seg_df = pd.DataFrame(rows)
        self._bulk_insert(seg_df, "segmentacion")
        log.info(f"Segmentaciones insertadas: {len(seg_df):,}")

    # ──────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────
    def _bulk_insert(self, df: pd.DataFrame, table: str) -> None:
        """Inserta DataFrame en lotes usando pandas to_sql."""
        with self.engine.begin() as conn:
            df.to_sql(
                table,
                conn,
                schema="produccion",
                if_exists="append",
                index=False,
                method="multi",
                chunksize=min(self.batch_size, 5_000),
            )

    def _fetch_map(
        self,
        query: str,
        cast_key=None,
        reverse: bool = False,
    ) -> dict:
        with self.engine.connect() as conn:
            rows = conn.execute(text(query))
            if reverse:
                return {row[1]: row[0] for row in rows}
            if cast_key:
                return {cast_key(row[0]): row[1] for row in rows}
            return {row[0]: row[1] for row in rows}

    def _update_etl_control(
        self,
        proceso: str,
        registros: int,
        ultimo_id: Optional[int] = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE produccion.etl_control
                    SET ultima_ejecucion       = NOW(),
                        registros_procesados   = :reg,
                        ultimo_id_procesado    = :uid,
                        estado_ultimo_proceso  = 'exitoso'
                    WHERE nombre_proceso = :proc
                """),
                {"proc": proceso, "reg": registros, "uid": ultimo_id},
            )

    # ──────────────────────────────────────────────────
    # PUNTO DE ENTRADA
    # ──────────────────────────────────────────────────
    def run(self) -> None:
        t0 = datetime.now()
        log.info("═" * 60)
        log.info("  INICIANDO CARGA COMPLETA  IBM → PostgreSQL")
        log.info("═" * 60)

        try:
            df = self.load_and_preprocess()

            merchant_map = self.load_merchants(df)
            usuario_map  = self.load_usuarios(df)
            tarjeta_map  = self.load_tarjetas(df, usuario_map)

            self.load_transacciones(df, usuario_map, merchant_map, tarjeta_map)
            self.load_fraude(df)
            self.load_demographics(usuario_map)
            self.load_dispositivos(df, usuario_map)
            self.load_aplicacion(df, usuario_map)
            self.load_segmentacion(df, usuario_map)

            self._update_etl_control("carga_inicial_ibm", len(df), int(df.index.max()))

            elapsed = (datetime.now() - t0).total_seconds()
            log.info(f"═" * 60)
            log.info(f"  CARGA COMPLETADA  en {elapsed:.1f}s")
            log.info(f"  Filas procesadas : {len(df):,}")
            log.info(f"  Merchants        : {len(merchant_map):,}")
            log.info(f"  Usuarios         : {len(usuario_map):,}")
            log.info(f"═" * 60)

        except Exception as exc:
            log.exception(f"ERROR CRÍTICO en carga: {exc}")
            with self.engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE produccion.etl_control
                        SET estado_ultimo_proceso = 'fallido',
                            ultima_ejecucion      = NOW()
                        WHERE nombre_proceso = 'carga_inicial_ibm'
                    """)
                )
            raise


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    csv_path = sys.argv[1] if len(sys.argv) > 1 else "credit_card_transactions.csv"
    etl = IBMDatasetETL(csv_path, batch_size=10_000)
    etl.run()
