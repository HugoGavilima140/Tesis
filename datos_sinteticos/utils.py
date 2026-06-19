"""
Utilidades compartidas: mapeos MCC, transformaciones de columnas IBM,
y generación de atributos sintéticos coherentes con el dominio financiero.
"""
from __future__ import annotations

import math
import random
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────
# MAPEOS COLUMNAS IBM → MODELO RELACIONAL
# ──────────────────────────────────────────────────────────────

# IBM [Use Chip] → canal en transacciones
CANAL_MAP: dict[str, str] = {
    "Chip Transaction":   "chip",
    "Swipe Transaction":  "banda_magnetica",
    "Online Transaction": "online",
}

# IBM [Errors?] → estado en transacciones
ERRORS_ESTADO_MAP: dict[str, str] = {
    "":                    "completada",
    "Insufficient Balance":"rechazada",
    "Bad CVV":             "rechazada",
    "Bad Card Number":     "rechazada",
    "Bad Expiration":      "rechazada",
    "Bad PIN":             "rechazada",
    "Bad Zipcode":         "rechazada",
    "Technical Glitch":    "error",
}

# IBM [MCC] → categoría legible
MCC_CATEGORY: dict[tuple[int, int], str] = {
    (742,  743):  "Veterinarios",
    (763,  764):  "Agricultura",
    (780,  781):  "Jardinería",
    (1000, 1500): "Minería y Petróleo",
    (1500, 2000): "Construcción",
    (2000, 3000): "Manufactura",
    (3000, 3351): "Aerolíneas",
    (3351, 3500): "Renta de Autos",
    (3500, 3731): "Hoteles y Alojamiento",
    (4111, 4114): "Transporte Local",
    (4121, 4122): "Taxis y Rideshare",
    (4511, 4513): "Aerolíneas",
    (4722, 4724): "Agencias de Viaje",
    (4814, 4817): "Telecomunicaciones",
    (4899, 4900): "Cable y Satélite",
    (4900, 4901): "Servicios Públicos",
    (5200, 5300): "Hogar y Jardín",
    (5300, 5400): "Tiendas de Descuento",
    (5400, 5500): "Supermercados",
    (5500, 5600): "Concesionarios Automotrices",
    (5541, 5543): "Gasolineras",
    (5600, 5700): "Moda y Ropa",
    (5700, 5800): "Muebles y Electrodomésticos",
    (5812, 5815): "Restaurantes y Comida Rápida",
    (5900, 5940): "Farmacia y Droguería",
    (5940, 5970): "Deportes y Hobbies",
    (5970, 6000): "Retail Especializado",
    (6010, 6012): "Bancos y ATM",
    (6100, 6200): "Crédito y Financiamiento",
    (6200, 6300): "Inversiones y Corretaje",
    (6300, 6400): "Seguros",
    (7000, 7100): "Hospitalidad",
    (7200, 7300): "Cuidado Personal y Lavandería",
    (7300, 7400): "Servicios Empresariales",
    (7372, 7374): "Software y TI",
    (7500, 7600): "Servicios Automotrices",
    (7800, 7900): "Entretenimiento y Recreación",
    (8000, 8100): "Salud y Bienestar",
    (8200, 8300): "Educación",
    (9000, 9100): "Gobierno",
}

MCC_SEGMENT: dict[tuple[int, int], str] = {
    (5400, 5500): "Supermercados y Alimentos",
    (5812, 5815): "Gastronomía",
    (5900, 5940): "Salud y Farmacia",
    (8000, 8100): "Salud y Bienestar",
    (5600, 5700): "Moda",
    (5940, 5970): "Deportes y Recreación",
    (5700, 5800): "Hogar",
    (3500, 3731): "Viajes y Hospitalidad",
    (4511, 4513): "Viajes y Hospitalidad",
    (4722, 4724): "Viajes y Hospitalidad",
    (7000, 7100): "Viajes y Hospitalidad",
    (6010, 6400): "Servicios Financieros",
    (4814, 4817): "Telecomunicaciones",
    (5500, 5600): "Automotriz",
    (5541, 5543): "Automotriz",
    (7500, 7600): "Automotriz",
    (8200, 8300): "Educación",
    (7300, 7400): "Servicios Empresariales",
    (7372, 7374): "Tecnología",
}

TIPO_TX_POR_MCC: dict[tuple[int, int], str] = {
    (6010, 6012): "retiro",
    (6100, 6400): "pago_servicio",
    (4900, 4901): "pago_servicio",
    (4814, 4817): "pago_servicio",
}

FRAUDE_TIPOS = [
    "monto_inusual",
    "ubicacion_anomala",
    "frecuencia_alta",
    "patron_sospechoso",
    "tarjeta_clonada",
    "identidad_robada",
    "otro",
]

MARCAS_TARJETA = ["Visa", "Mastercard", "Amex", "Discover"]

DEVICE_TYPES = ["mobile", "tablet", "desktop"]
OS_MAP = {
    "mobile":  ["iOS", "Android"],
    "tablet":  ["iOS", "Android", "Windows"],
    "desktop": ["Windows", "macOS", "Linux"],
}
APP_VERSIONS = ["3.1.0", "3.2.1", "4.0.0", "4.1.2", "4.2.0"]
CANALES_ADQUISICION = ["organic", "paid_search", "social_media", "referral", "email"]

RANGOS_EDAD = ["18-25", "26-35", "36-50", "51-65", "65+"]
GENEROS = ["M", "F", "O"]
NIVELES_INGRESO = ["bajo", "medio_bajo", "medio", "medio_alto", "alto"]
OCUPACIONES = [
    "empleado", "profesional", "empresario", "estudiante",
    "independiente", "jubilado", "otro",
]

# ──────────────────────────────────────────────────────────────
# FUNCIONES DE LOOKUP
# ──────────────────────────────────────────────────────────────

def mcc_to_category(mcc: int) -> str:
    for (lo, hi), cat in MCC_CATEGORY.items():
        if lo <= mcc < hi:
            return cat
    return "Retail Misceláneo"


def mcc_to_segment(mcc: int) -> str:
    for (lo, hi), seg in MCC_SEGMENT.items():
        if lo <= mcc < hi:
            return seg
    return "Otros"


def mcc_to_tipo_tx(mcc: int) -> str:
    for (lo, hi), tipo in TIPO_TX_POR_MCC.items():
        if lo <= mcc < hi:
            return tipo
    return "compra"


# ──────────────────────────────────────────────────────────────
# TRANSFORMACIONES IBM
# ──────────────────────────────────────────────────────────────

def parse_amount(raw: str) -> float:
    """Convierte '$-123.45' o '123.45' a float."""
    cleaned = str(raw).replace("$", "").replace(",", "").strip()
    return float(cleaned)


def parse_ibm_datetime(row: pd.Series) -> datetime:
    """Reconstruye timestamp desde columnas Year, Month, Day, Time."""
    t = str(row["Time"]).strip()
    if ":" in t:
        hour, minute = t.split(":")
    else:
        t = t.zfill(4)
        hour, minute = t[:2], t[2:]
    return datetime(
        int(row["Year"]), int(row["Month"]), int(row["Day"]),
        int(hour), int(minute),
    )


def map_canal(use_chip: str) -> str:
    return CANAL_MAP.get(str(use_chip).strip(), "otro")


def map_estado(error_val) -> str:
    key = "" if pd.isna(error_val) else str(error_val).strip()
    return ERRORS_ESTADO_MAP.get(key, "completada")


def is_fraud(val) -> bool:
    return str(val).strip().upper() == "YES"


def riesgo_score_from_fraud(flag: bool) -> float:
    return 0.95 if flag else round(random.uniform(0.01, 0.15), 4)


# ──────────────────────────────────────────────────────────────
# CÁLCULOS FINANCIEROS
# ──────────────────────────────────────────────────────────────

COSTO_OPERATIVO_RATE = 0.008   # 0.8 %
COMISION_RATE        = 0.018   # 1.8 %


def calc_costo_operativo(monto: float) -> float:
    return round(abs(monto) * COSTO_OPERATIVO_RATE, 4)


def calc_ingreso_comision(monto: float) -> float:
    return round(abs(monto) * COMISION_RATE, 4)


# ──────────────────────────────────────────────────────────────
# SCORES DE USUARIOS
# ──────────────────────────────────────────────────────────────

def nivel_riesgo_from_pct(pct_fraude: float) -> str:
    if pct_fraude < 0.01:
        return "bajo"
    if pct_fraude < 0.05:
        return "medio"
    if pct_fraude < 0.15:
        return "alto"
    return "critico"


def score_actividad(n_tx: int, max_log: float) -> float:
    if max_log == 0:
        return 0.0
    return round(math.log1p(n_tx) / max_log * 100, 2)


def score_rentabilidad(monto_total: float, max_monto: float) -> float:
    if max_monto == 0:
        return 0.0
    return round(monto_total / max_monto * 100, 2)


def segmento_transaccional(n_tx: int, percentiles: tuple) -> str:
    p25, p50, p75 = percentiles
    if n_tx >= p75:
        return "alto_volumen"
    if n_tx >= p50:
        return "frecuente"
    if n_tx >= p25:
        return "esporadico"
    return "inactivo"


def segmento_rentabilidad_label(score: float) -> str:
    if score >= 75:
        return "platinum"
    if score >= 50:
        return "gold"
    if score >= 25:
        return "silver"
    return "bronze"


# ──────────────────────────────────────────────────────────────
# GENERADORES SINTÉTICOS
# ──────────────────────────────────────────────────────────────

def gen_device_type() -> str:
    return random.choices(DEVICE_TYPES, weights=[0.65, 0.20, 0.15])[0]


def gen_os(device_type: str) -> str:
    return random.choice(OS_MAP.get(device_type, ["otro"]))


def gen_app_version() -> str:
    return random.choice(APP_VERSIONS)


def gen_canal_adquisicion() -> str:
    return random.choices(
        CANALES_ADQUISICION, weights=[0.30, 0.25, 0.20, 0.15, 0.10]
    )[0]


def gen_tarjeta_marca() -> str:
    return random.choices(
        MARCAS_TARJETA, weights=[0.45, 0.35, 0.12, 0.08]
    )[0]


def gen_rango_edad() -> str:
    return random.choices(
        RANGOS_EDAD, weights=[0.18, 0.30, 0.28, 0.16, 0.08]
    )[0]


def gen_genero() -> str:
    return random.choices(GENEROS, weights=[0.49, 0.49, 0.02])[0]


def gen_nivel_ingreso() -> str:
    return random.choices(
        NIVELES_INGRESO, weights=[0.15, 0.25, 0.35, 0.18, 0.07]
    )[0]


def gen_ocupacion() -> str:
    return random.choices(
        OCUPACIONES, weights=[0.35, 0.25, 0.12, 0.10, 0.10, 0.05, 0.03]
    )[0]


def gen_fraud_tipo() -> str:
    return random.choices(
        FRAUDE_TIPOS, weights=[0.25, 0.20, 0.20, 0.15, 0.10, 0.05, 0.05]
    )[0]


def gen_engagement_score(n_tx: int) -> float:
    """Engagement correlacionado con actividad, con ruido."""
    base = min(math.log1p(n_tx) * 12, 100)
    noise = random.gauss(0, 5)
    return round(max(0, min(100, base + noise)), 2)


def gen_limite_credito(tipo_tarjeta: str) -> Optional[float]:
    if tipo_tarjeta == "debito":
        return None
    limits = {"credito": (500, 25000), "prepago": (50, 2000), "virtual": (100, 5000)}
    lo, hi = limits.get(tipo_tarjeta, (500, 10000))
    return round(random.uniform(lo, hi), 2)
