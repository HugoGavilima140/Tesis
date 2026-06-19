#!/usr/bin/env python3
# Forzar locale C antes de importar psycopg2 para que libpq use mensajes
# de error en ASCII y evitar UnicodeDecodeError en Windows con locale español.
import os
os.environ.setdefault("LC_ALL", "C")
os.environ.setdefault("LC_MESSAGES", "C")
os.environ.setdefault("PGPASSFILE", "NUL")   # evita leer pgpass en cp1252
"""
Generador de datos sintéticos para el esquema produccion (Fintech IBM).
Respeta todas las FK, CHECK constraints y distribuciones documentadas en el
DICCIONARIO_DE_DATOS.md.

Uso:
    python generate_synthetic_data.py [--usuarios N] [--merchants N]
                                      [--campanas N] [--seed N] [--truncate]

Opciones:
    --usuarios   Número de usuarios a generar  (default: 200)
    --merchants  Número de merchants           (default: 100)
    --campanas   Número de campañas            (default: 12)
    --seed       Semilla aleatoria             (default: 42)
    --truncate   Truncar tablas antes de insertar
"""
import argparse
import math
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(__file__))
from config import db_config, setup_logging

logger = setup_logging("generate_synthetic_data")

# ──────────────────────────────────────────────────────────────────────────────
# Parámetros por defecto
# ──────────────────────────────────────────────────────────────────────────────
N_USUARIOS   = 200
N_MERCHANTS  = 100
N_CAMPANAS   = 12
FRAUD_RATE   = 0.025          # ~2.5 % de fraude (similar al IBM dataset)
DATE_START   = date(2010, 1, 1)
DATE_END     = date(2019, 12, 31)
TX_RANGE     = (15, 120)      # rango de transacciones por usuario
SEED         = 42

# ──────────────────────────────────────────────────────────────────────────────
# Lookup MCC  (mcc_code, categoria, segmento, peso_relativo)
# ──────────────────────────────────────────────────────────────────────────────
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
    (5715, "Licorerias",                "Gastronomia",             1),
    (5441, "Dulcerias",                 "Alimentacion",            1),
    (5943, "Papeleria",                 "Retail",                  1),
]

MCC_CODES   = [m[0] for m in MCC_DATA]
MCC_CAT     = {m[0]: m[1] for m in MCC_DATA}
MCC_SEG     = {m[0]: m[2] for m in MCC_DATA}
MCC_WEIGHTS = [m[3] for m in MCC_DATA]

# ──────────────────────────────────────────────────────────────────────────────
# Ciudades/estados USA
# ──────────────────────────────────────────────────────────────────────────────
US_CITIES = [
    ("New York",       "NY", "10001"),
    ("Los Angeles",    "CA", "90001"),
    ("Chicago",        "IL", "60601"),
    ("Houston",        "TX", "77001"),
    ("Phoenix",        "AZ", "85001"),
    ("Philadelphia",   "PA", "19101"),
    ("San Antonio",    "TX", "78201"),
    ("San Diego",      "CA", "92101"),
    ("Dallas",         "TX", "75201"),
    ("San Jose",       "CA", "95101"),
    ("Austin",         "TX", "73301"),
    ("Jacksonville",   "FL", "32099"),
    ("Charlotte",      "NC", "28201"),
    ("Columbus",       "OH", "43085"),
    ("San Francisco",  "CA", "94101"),
    ("Seattle",        "WA", "98101"),
    ("Denver",         "CO", "80201"),
    ("Nashville",      "TN", "37201"),
    ("Miami",          "FL", "33101"),
    ("Atlanta",        "GA", "30301"),
]

# Nombres de comercio por segmento
MERCHANT_NAMES = {
    "Retail":                ["MartPlus", "ShopHub", "BuyMore", "QuickMart", "ValueShop"],
    "Gastronomia":           ["Tasty Bites", "Urban Kitchen", "The Grill", "Spice House", "Bistro 7"],
    "Salud":                 ["HealthCare Plus", "MedPoint", "PharmaCare", "Wellness Hub", "CityPharm"],
    "Combustible":           ["FuelStop", "QuickGas", "EnergyFill", "SpeedFuel", "GasXpress"],
    "Servicios Financieros": ["ATM Service", "BankPlus", "CashPoint", "FinanceHub"],
    "Tecnologia":            ["TechWorld", "DigiStore", "ByteZone", "GadgetHub"],
    "Viajes y Hospedaje":    ["ComfortInn", "TravelRest", "SleepEasy", "CityLodge"],
    "Transporte":            ["RideCity", "TransitHub", "QuickRide", "UrbanMove"],
    "Moda":                  ["FashionFit", "StyleZone", "TrendWear", "ChicShop"],
    "Telecomunicaciones":    ["TelecomPlus", "ConnectHub", "DataLink"],
    "Entretenimiento":       ["CinePlex", "FunZone", "EventHub"],
    "Construccion":          ["BuilderPro", "HomeDepotPlus", "FixItStore"],
    "Alimentacion":          ["SweetTreat", "BakeryCo", "SnackHub"],
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def new_uuid() -> str:
    return str(uuid.uuid4())


def wchoice(choices, weights):
    return random.choices(choices, weights=weights, k=1)[0]


def rand_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))


def rand_dt(start: date, end: date) -> datetime:
    d = rand_date(start, end)
    return datetime(d.year, d.month, d.day,
                    random.randint(0, 23), random.randint(0, 59), random.randint(0, 59))


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ──────────────────────────────────────────────────────────────────────────────
# Generadores por tabla
# ──────────────────────────────────────────────────────────────────────────────

def gen_usuarios(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        city, _, _ = random.choice(US_CITIES)
        rows.append({
            "usuario_id":         new_uuid(),
            "customer_id_origen": i,
            "fecha_registro":     rand_date(DATE_START, date(2012, 12, 31)),
            "estado":             wchoice(["activo", "inactivo", "suspendido", "bloqueado"],
                                          [80, 12, 5, 3]),
            "tipo_usuario":       wchoice(["individual", "premium", "empresarial", "basico"],
                                          [55, 20, 15, 10]),
            "nivel_riesgo":       wchoice(["bajo", "medio", "alto", "critico"],
                                          [60, 25, 12, 3]),
            "pais":               "USA",
            "ciudad":             city,
            "score_actividad":    None,   # se recalcula tras generar transacciones
            "score_rentabilidad": None,
        })
    return rows


def gen_dispositivos(usuarios: list[dict]) -> list[dict]:
    os_map = {
        "mobile":  (["iOS", "Android"],            [50, 50]),
        "tablet":  (["iOS", "Android"],            [55, 45]),
        "desktop": (["Windows", "macOS", "Linux"], [65, 25, 10]),
    }
    versions = ["2.1.0", "2.3.1", "2.5.0", "3.0.0", "3.1.2", "3.2.0", "4.0.1"]

    rows = []
    for u in usuarios:
        n_dev = wchoice([1, 2, 3], [60, 30, 10])
        for _ in range(n_dev):
            dtype = wchoice(["mobile", "tablet", "desktop"], [65, 20, 15])
            os_list, os_w = os_map[dtype]
            primer = u["fecha_registro"] + timedelta(days=random.randint(0, 30))
            rows.append({
                "dispositivo_id":    new_uuid(),
                "usuario_id":        u["usuario_id"],
                "device_type":       dtype,
                "sistema_operativo": wchoice(os_list, os_w),
                "version_app":       random.choice(versions),
                "fecha_primer_uso":  primer,
                "fecha_ultimo_uso":  rand_date(primer, DATE_END),
                "estado_dispositivo": wchoice(["activo", "inactivo", "bloqueado", "eliminado"],
                                              [75, 15, 5, 5]),
            })
    return rows


def gen_merchants(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        mid = i + 1000
        mcc = wchoice(MCC_CODES, MCC_WEIGHTS)
        seg = MCC_SEG[mcc]
        city, state, zipcode = random.choice(US_CITIES)
        name_pool = MERCHANT_NAMES.get(seg, ["GenericShop"])
        nombre = f"{random.choice(name_pool)} #{mid % 100:02d}"

        rows.append({
            "merchant_id":        new_uuid(),
            "merchant_id_origen": mid,
            "nombre_comercio":    nombre,
            "categoria":          MCC_CAT[mcc],
            "mcc_code":           mcc,
            "segmento":           seg,
            "ciudad":             city,
            "estado_region":      state,
            "zip_code":           zipcode,
            "pais":               "USA",
            "fecha_afiliacion":   date(2018, 1, 1),
            "estado":             wchoice(["activo", "inactivo", "suspendido"], [90, 7, 3]),
        })
    return rows


def gen_demographics(usuarios: list[dict]) -> list[dict]:
    ocupaciones = [
        "Empleado", "Profesional independiente", "Empresario",
        "Estudiante", "Jubilado", "Desempleado", "Ama de casa",
    ]
    rows = []
    for u in usuarios:
        year_reg  = u["fecha_registro"].year
        antiguedad = date.today().year - year_reg
        rows.append({
            "usuario_id":              u["usuario_id"],
            "rango_edad":              wchoice(["18-25", "26-35", "36-50", "51+"],
                                               [15, 35, 35, 15]),
            "genero":                  wchoice(["M", "F", "O", None], [48, 48, 2, 2]),
            "ocupacion":               random.choice(ocupaciones),
            "nivel_ingresos_estimado": wchoice(["bajo", "medio_bajo", "medio", "medio_alto", "alto"],
                                               [10, 20, 35, 25, 10]),
            "antiguedad_cliente":      max(0, antiguedad),
        })
    return rows


def gen_segmentacion(usuarios: list[dict]) -> list[dict]:
    risk_map = {
        "critico": ("critico", "platinum", "alto_volumen"),
        "alto":    ("alto",    "gold",     "frecuente"),
        "medio":   ("medio",   "silver",   "esporadico"),
        "bajo":    ("bajo",    "bronze",   "esporadico"),
    }
    seg_tx   = ["alto_volumen", "frecuente", "esporadico", "inactivo"]
    seg_rent = ["platinum", "gold", "silver", "bronze"]

    rows = []
    for u in usuarios:
        sr, srr, stx = risk_map.get(u["nivel_riesgo"], ("medio", "silver", "esporadico"))
        if random.random() < 0.30:
            stx = random.choice(seg_tx)
        if random.random() < 0.30:
            srr = random.choice(seg_rent)
        rows.append({
            "segmentacion_id":        new_uuid(),
            "usuario_id":             u["usuario_id"],
            "segmento_transaccional": stx,
            "segmento_rentabilidad":  srr,
            "segmento_riesgo":        sr,
            "cluster_ml":             random.randint(0, 7),
            "fecha_segmentacion":     DATE_START,
        })
    return rows


def gen_tarjetas(usuarios: list[dict]) -> list[dict]:
    marcas = ["Visa", "Mastercard", "Amex", "Discover"]
    marc_w = [45, 35, 12, 8]
    estados = ["activa", "inactiva", "bloqueada", "vencida", "cancelada"]
    estado_w = [80, 8, 5, 4, 3]

    rows = []
    card_counter = 0
    for u in usuarios:
        n_cards = wchoice([1, 2, 3], [55, 35, 10])
        for _ in range(n_cards):
            canal_raw = wchoice(["chip", "swipe", "online"], [50, 25, 25])
            if canal_raw == "online":
                tipo_tarjeta = "virtual"
                limite = None
            elif random.random() < 0.40:
                tipo_tarjeta = "credito"
                limite = float(random.choice([1000, 2000, 3000, 5000, 7500, 10000, 15000, 20000]))
            else:
                tipo_tarjeta = "debito"
                limite = None

            fecha_emision = u["fecha_registro"] + timedelta(days=random.randint(-30, 10))
            if fecha_emision < DATE_START:
                fecha_emision = DATE_START

            rows.append({
                "tarjeta_id":     new_uuid(),
                "card_id_origen": card_counter,
                "usuario_id":     u["usuario_id"],
                "tipo_tarjeta":   tipo_tarjeta,
                "marca":          wchoice(marcas, marc_w),
                "estado":         wchoice(estados, estado_w),
                "fecha_emision":  fecha_emision,
                "limite_credito": limite,
                "score_uso":      round(clamp(float(np.random.normal(60, 20)), 5.0, 99.0), 2),
            })
            card_counter += 1
    return rows


def gen_aplicacion(usuarios: list[dict]) -> list[dict]:
    versiones = ["1.0.0", "1.5.2", "2.0.0", "2.3.1", "3.0.0", "3.2.1"]
    canales   = ["organic", "paid_search", "social_media", "referral", "email", "otro"]
    canal_w   = [30, 20, 25, 15, 7, 3]

    rows = []
    for u in usuarios:
        n_tx_est = random.randint(*TX_RANGE)
        eng = clamp(math.log1p(n_tx_est) * 12 + float(np.random.normal(0, 5)), 0.0, 100.0)
        rows.append({
            "app_id":            new_uuid(),
            "usuario_id":        u["usuario_id"],
            "version":           random.choice(versiones),
            "canal_adquisicion": wchoice(canales, canal_w),
            "fecha_activacion":  None,
            "estado":            wchoice(["activa", "inactiva", "desinstalada"], [80, 12, 8]),
            "engagement_score":  round(eng, 2),
        })
    return rows


def gen_transacciones(
    usuarios: list[dict],
    merchants: list[dict],
    tarjetas: list[dict],
) -> list[dict]:
    cards_by_user: dict[str, list] = {}
    for t in tarjetas:
        cards_by_user.setdefault(t["usuario_id"], []).append(t["tarjeta_id"])

    merchant_ids = [m["merchant_id"] for m in merchants]
    merchant_mcc = {m["merchant_id"]: m["mcc_code"] for m in merchants}

    canales   = ["chip", "banda_magnetica", "online", "nfc", "atm", "transferencia", "otro"]
    canal_w   = [35, 20, 25, 10, 5, 4, 1]
    estados   = ["completada", "pendiente", "rechazada", "revertida", "error"]
    estado_w  = [88, 5, 4, 2, 1]
    tipo_tx   = ["compra", "transferencia", "pago_servicio", "recarga"]
    tipo_tx_w = [75, 10, 10, 5]

    rows = []
    tx_counter = 0

    for u in usuarios:
        uid = u["usuario_id"]
        user_cards = cards_by_user.get(uid, [None])
        n_tx = random.randint(*TX_RANGE)

        for _ in range(n_tx):
            mid = random.choice(merchant_ids)
            mcc = merchant_mcc[mid]

            tipo = "retiro" if mcc in (6011, 6012) else wchoice(tipo_tx, tipo_tx_w)

            if tipo == "retiro":
                monto = float(random.choice([20, 40, 60, 80, 100, 200, 300, 500]))
            else:
                raw = float(np.random.lognormal(mean=3.5, sigma=1.2))
                monto = round(max(0.01, raw), 2)

            is_fraud = random.random() < FRAUD_RATE
            riesgo   = (round(random.uniform(0.70, 0.99), 4) if is_fraud
                        else round(random.uniform(0.01, 0.15), 4))

            fecha_tx = rand_dt(DATE_START, DATE_END)
            tarjeta_id = (random.choice(user_cards)
                          if user_cards and random.random() > 0.10 else None)

            monto_abs = abs(monto)
            rows.append({
                "transaccion_id":        new_uuid(),
                "transaction_id_origen": tx_counter,
                "usuario_origen_id":     uid,
                "usuario_destino_id":    None,
                "merchant_id":           mid,
                "tarjeta_id":            tarjeta_id,
                "fecha_transaccion":     fecha_tx,
                "tipo_transaccion":      tipo,
                "subtipo_transaccion":   MCC_CAT.get(mcc, "Otro"),
                "monto":                 monto,
                "moneda":                "USD",
                "canal":                 wchoice(canales, canal_w),
                "estado":                wchoice(estados, estado_w),
                "costo_operativo":       round(monto_abs * 0.008, 4),
                "ingreso_comision":      round(monto_abs * 0.018, 4),
                "riesgo_score":          riesgo,
                "_is_fraud":             is_fraud,   # campo auxiliar, no se inserta
            })
            tx_counter += 1

    return rows


def gen_fraude(transacciones: list[dict]) -> list[dict]:
    tipos_alerta = [
        "monto_inusual", "ubicacion_anomala", "frecuencia_alta",
        "patron_sospechoso", "tarjeta_clonada", "identidad_robada", "otro",
    ]
    alerta_w_fraud = [20, 20, 15, 20, 10, 10, 5]

    rows = []
    for t in transacciones:
        is_fraud = t["_is_fraud"]
        rows.append({
            "fraude_id":         new_uuid(),
            "transaccion_id":    t["transaccion_id"],
            "fecha_transaccion": t["fecha_transaccion"],
            "flag_fraude":       is_fraud,
            "tipo_alerta":       wchoice(tipos_alerta, alerta_w_fraud) if is_fraud else None,
            "score_fraude":      (round(random.uniform(0.70, 0.99), 4) if is_fraud
                                  else round(random.uniform(0.01, 0.20), 4)),
            "modelo_detector":   "IBM_Label_v1",
            "fecha_deteccion":   t["fecha_transaccion"],
            "estado_revision":   "confirmado" if is_fraud else "descartado",
        })
    return rows


def gen_campanas(n: int) -> list[dict]:
    tipos   = ["email", "whatsapp", "push", "sms", "mixta", "inapp"]
    tipos_w = [30, 20, 20, 15, 10, 5]
    estados = ["planificada", "activa", "pausada", "finalizada", "cancelada"]
    segs    = ["alto_volumen", "frecuente", "esporadico", "inactivo", None]
    nombres = [
        "Bienvenida Premium", "Cashback Verano", "Reactivacion Clientes",
        "Cross-sell Credito", "Fidelizacion Gold", "Educacion Anti-Fraude",
        "Promo Navidad", "Descarga App", "Programa Referidos", "Upgrade Limite",
        "Seguro de Viaje", "Puntos Dobles Q4", "Campana Q1 Retail",
        "Campana Q2 Finanzas", "Campana Q3 Viajes", "Campana Q4 Moda",
    ]
    rows = []
    for i in range(n):
        fecha_ini = rand_date(date(2016, 1, 1), date(2019, 6, 1))
        fecha_fin = fecha_ini + timedelta(days=random.randint(7, 90))
        nombre = nombres[i % len(nombres)]
        if i >= len(nombres):
            nombre += f" #{i + 1}"
        rows.append({
            "campana_id":        new_uuid(),
            "nombre":            nombre,
            "tipo":              wchoice(tipos, tipos_w),
            "fecha_inicio":      fecha_ini,
            "fecha_fin":         fecha_fin,
            "segmento_objetivo": random.choice(segs),
            "presupuesto":       round(random.uniform(1_000, 50_000), 2),
            "estado":            wchoice(estados, [10, 30, 10, 45, 5]),
        })
    return rows


def gen_pagos(campanas: list[dict], usuarios: list[dict]) -> list[dict]:
    estados   = ["pendiente", "procesado", "fallido", "revertido"]
    estado_w  = [20, 65, 10, 5]

    rows = []
    for c in campanas:
        n_pags = max(1, int(len(usuarios) * random.uniform(0.05, 0.20)))
        sample = random.sample(usuarios, min(n_pags, len(usuarios)))
        for u in sample:
            rows.append({
                "pago_id":         new_uuid(),
                "campana_id":      c["campana_id"],
                "usuario_id":      u["usuario_id"],
                "monto_incentivo": round(random.uniform(0.5, 50.0), 2),
                "fecha_pago":      c["fecha_inicio"] + timedelta(days=random.randint(0, 30)),
                "estado_pago":     wchoice(estados, estado_w),
            })
    return rows


def gen_braze_email_envios(campanas: list[dict], usuarios: list[dict]) -> list[dict]:
    templates = ["bienvenida_v1", "promo_v2", "reactivacion_v1", "alerta_v1", "newsletter_v3"]
    estados   = ["enviado", "entregado", "rebotado", "bloqueado", "fallido"]
    estado_w  = [15, 70, 7, 5, 3]

    rows = []
    for c in campanas:
        if c["tipo"] not in ("email", "mixta"):
            continue
        n = max(1, int(len(usuarios) * random.uniform(0.10, 0.40)))
        sample = random.sample(usuarios, min(n, len(usuarios)))
        for u in sample:
            d = c["fecha_inicio"] + timedelta(days=random.randint(0, 5))
            rows.append({
                "envio_id":       new_uuid(),
                "campana_id":     c["campana_id"],
                "usuario_id":     u["usuario_id"],
                "fecha_envio":    datetime(d.year, d.month, d.day, random.randint(8, 20), 0, 0),
                "template":       random.choice(templates),
                "estado_entrega": wchoice(estados, estado_w),
            })
    return rows


def gen_braze_wa_envios(campanas: list[dict], usuarios: list[dict]) -> list[dict]:
    templates = ["wa_promo_v1", "wa_alerta_v1", "wa_bienvenida_v1", "wa_encuesta_v1"]
    estados   = ["enviado", "entregado", "leido", "fallido", "bloqueado"]
    estado_w  = [10, 35, 45, 7, 3]

    rows = []
    for c in campanas:
        if c["tipo"] not in ("whatsapp", "mixta"):
            continue
        n = max(1, int(len(usuarios) * random.uniform(0.05, 0.25)))
        sample = random.sample(usuarios, min(n, len(usuarios)))
        for u in sample:
            d = c["fecha_inicio"] + timedelta(days=random.randint(0, 3))
            rows.append({
                "envio_id":       new_uuid(),
                "campana_id":     c["campana_id"],
                "usuario_id":     u["usuario_id"],
                "fecha_envio":    datetime(d.year, d.month, d.day, random.randint(9, 21), 0, 0),
                "template":       random.choice(templates),
                "estado_entrega": wchoice(estados, estado_w),
            })
    return rows


def gen_braze_email_lectura(envios: list[dict]) -> list[dict]:
    rows = []
    for e in envios:
        if e["estado_entrega"] != "entregado":
            continue
        opened = random.random() < 0.35   # 35% open rate realista
        rows.append({
            "lectura_id":    new_uuid(),
            "envio_id":      e["envio_id"],
            "usuario_id":    e["usuario_id"],
            "fecha_lectura": (e["fecha_envio"] + timedelta(hours=random.randint(1, 72))
                              if opened else None),
            "opened_flag":   opened,
        })
    return rows


def gen_braze_wa_lectura(envios: list[dict]) -> list[dict]:
    rows = []
    for e in envios:
        if e["estado_entrega"] not in ("leido", "entregado"):
            continue
        opened = e["estado_entrega"] == "leido" or random.random() < 0.50
        rows.append({
            "lectura_id":    new_uuid(),
            "envio_id":      e["envio_id"],
            "usuario_id":    e["usuario_id"],
            "fecha_lectura": (e["fecha_envio"] + timedelta(hours=random.randint(0, 24))
                              if opened else None),
            "opened_flag":   opened,
        })
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Recálculo de scores
# ──────────────────────────────────────────────────────────────────────────────

def recalc_scores(usuarios: list[dict], transacciones: list[dict]) -> None:
    from collections import defaultdict

    count_tx: dict[str, int]   = defaultdict(int)
    vol_tx:   dict[str, float] = defaultdict(float)

    for t in transacciones:
        uid = t["usuario_origen_id"]
        count_tx[uid] += 1
        vol_tx[uid]   += abs(t["monto"])

    max_log = max((math.log1p(v) for v in count_tx.values()), default=1.0)
    max_vol = max(vol_tx.values(), default=1.0)

    for u in usuarios:
        uid = u["usuario_id"]
        u["score_actividad"]    = round(math.log1p(count_tx.get(uid, 0)) / max_log * 100, 2)
        u["score_rentabilidad"] = round(vol_tx.get(uid, 0.0) / max_vol * 100, 2)


# ──────────────────────────────────────────────────────────────────────────────
# Inserción en PostgreSQL
# ──────────────────────────────────────────────────────────────────────────────

def insert_batch(cur, table: str, rows: list[dict], cols: list[str], page_size: int = 1000) -> None:
    if not rows:
        logger.warning("  %s: sin filas, omitido.", table)
        return
    values = [[r.get(c) for c in cols] for r in rows]
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s ON CONFLICT DO NOTHING"
    execute_values(cur, sql, values, page_size=page_size)
    logger.info("  %s: %d filas insertadas.", table, len(rows))


def update_scores_db(cur, usuarios: list[dict]) -> None:
    for u in usuarios:
        cur.execute(
            "UPDATE produccion.usuarios SET score_actividad=%s, score_rentabilidad=%s "
            "WHERE usuario_id=%s",
            (u["score_actividad"], u["score_rentabilidad"], u["usuario_id"]),
        )
    logger.info("  Scores de %d usuarios actualizados.", len(usuarios))


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generador de datos sintéticos Fintech IBM")
    parser.add_argument("--usuarios",  type=int, default=N_USUARIOS)
    parser.add_argument("--merchants", type=int, default=N_MERCHANTS)
    parser.add_argument("--campanas",  type=int, default=N_CAMPANAS)
    parser.add_argument("--seed",      type=int, default=SEED)
    parser.add_argument("--truncate",  action="store_true",
                        help="Truncar todas las tablas antes de insertar")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    logger.info("=== Generador de datos sintéticos Fintech IBM ===")
    logger.info("Parámetros: usuarios=%d  merchants=%d  campañas=%d  seed=%d  truncate=%s",
                args.usuarios, args.merchants, args.campanas, args.seed, args.truncate)

    # ── Generación en memoria ────────────────────────────────────────────────
    logger.info("[1/12] Generando usuarios...")
    usuarios = gen_usuarios(args.usuarios)

    logger.info("[2/12] Generando merchants...")
    merchants = gen_merchants(args.merchants)

    logger.info("[3/12] Generando tarjetas...")
    tarjetas = gen_tarjetas(usuarios)

    logger.info("[4/12] Generando transacciones...")
    transacciones = gen_transacciones(usuarios, merchants, tarjetas)

    logger.info("[5/12] Recalculando scores de usuarios...")
    recalc_scores(usuarios, transacciones)

    logger.info("[6/12] Generando dispositivos, demographics, segmentacion, aplicacion...")
    dispositivos = gen_dispositivos(usuarios)
    demographics = gen_demographics(usuarios)
    segmentacion = gen_segmentacion(usuarios)
    aplicacion   = gen_aplicacion(usuarios)

    logger.info("[7/12] Generando fraude...")
    fraude = gen_fraude(transacciones)

    logger.info("[8/12] Generando campanas...")
    campanas = gen_campanas(args.campanas)

    logger.info("[9/12] Generando pagos...")
    pagos = gen_pagos(campanas, usuarios)

    logger.info("[10/12] Generando braze_email_envios y braze_wa_envios...")
    email_envios = gen_braze_email_envios(campanas, usuarios)
    wa_envios    = gen_braze_wa_envios(campanas, usuarios)

    logger.info("[11/12] Generando braze lecturas...")
    email_lect = gen_braze_email_lectura(email_envios)
    wa_lect    = gen_braze_wa_lectura(wa_envios)

    n_fraud = sum(1 for f in fraude if f["flag_fraude"])
    logger.info(
        "[12/12] Resumen: %d usuarios | %d merchants | %d tarjetas | "
        "%d transacciones (%.1f%% fraude) | %d campanas | %d pagos | "
        "%d email_envios | %d wa_envios",
        len(usuarios), len(merchants), len(tarjetas),
        len(transacciones), n_fraud / len(transacciones) * 100,
        len(campanas), len(pagos), len(email_envios), len(wa_envios),
    )

    # ── Inserción en PostgreSQL ──────────────────────────────────────────────
    logger.info("Conectando a PostgreSQL (host=%s db=%s user=%s)...",
                db_config.host, db_config.database, db_config.user)
    try:
        conn = psycopg2.connect(
            host=db_config.host,
            port=db_config.port,
            dbname=db_config.database,
            user=db_config.user,
            password=db_config.password,
        )
    except UnicodeDecodeError as ude:
        # psycopg2 en Windows con locale español falla al decodificar el
        # mensaje de error de libpq (cp1252 vs UTF-8). Re-lanzamos con contexto.
        raise RuntimeError(
            f"psycopg2 no pudo decodificar el mensaje de error de PostgreSQL "
            f"(UnicodeDecodeError en pos {ude.start}). "
            f"Verifica que la contraseña en .env sea correcta y que el servidor "
            f"esté corriendo: host={db_config.host} db={db_config.database} "
            f"user={db_config.user}"
        ) from ude
    conn.autocommit = False
    cur = conn.cursor()

    try:
        if args.truncate:
            logger.info("Truncando tablas (CASCADE)...")
            cur.execute("""
                TRUNCATE
                    produccion.braze_whatsapp_lectura,
                    produccion.braze_email_lectura,
                    produccion.braze_whatsapp_envios,
                    produccion.braze_email_envios,
                    produccion.pagos,
                    produccion.campanas,
                    produccion.fraude,
                    produccion.transacciones,
                    produccion.aplicacion,
                    produccion.segmentacion,
                    produccion.tarjetas,
                    produccion.usuarios_demographics,
                    produccion.dispositivos,
                    produccion.merchants,
                    produccion.usuarios
                CASCADE;
            """)

        # Orden estricto de FK: padres antes que hijos
        insert_batch(cur, "produccion.usuarios", usuarios, [
            "usuario_id", "customer_id_origen", "fecha_registro", "estado",
            "tipo_usuario", "nivel_riesgo", "pais", "ciudad",
            "score_actividad", "score_rentabilidad",
        ])

        insert_batch(cur, "produccion.merchants", merchants, [
            "merchant_id", "merchant_id_origen", "nombre_comercio", "categoria",
            "mcc_code", "segmento", "ciudad", "estado_region", "zip_code",
            "pais", "fecha_afiliacion", "estado",
        ])

        insert_batch(cur, "produccion.dispositivos", dispositivos, [
            "dispositivo_id", "usuario_id", "device_type", "sistema_operativo",
            "version_app", "fecha_primer_uso", "fecha_ultimo_uso", "estado_dispositivo",
        ])

        insert_batch(cur, "produccion.usuarios_demographics", demographics, [
            "usuario_id", "rango_edad", "genero", "ocupacion",
            "nivel_ingresos_estimado", "antiguedad_cliente",
        ])

        insert_batch(cur, "produccion.segmentacion", segmentacion, [
            "segmentacion_id", "usuario_id", "segmento_transaccional",
            "segmento_rentabilidad", "segmento_riesgo", "cluster_ml", "fecha_segmentacion",
        ])

        insert_batch(cur, "produccion.tarjetas", tarjetas, [
            "tarjeta_id", "card_id_origen", "usuario_id", "tipo_tarjeta", "marca",
            "estado", "fecha_emision", "limite_credito", "score_uso",
        ])

        insert_batch(cur, "produccion.aplicacion", aplicacion, [
            "app_id", "usuario_id", "version", "canal_adquisicion",
            "fecha_activacion", "estado", "engagement_score",
        ])

        # margen es GENERATED ALWAYS AS → no se incluye en INSERT
        insert_batch(cur, "produccion.transacciones", transacciones, [
            "transaccion_id", "transaction_id_origen", "usuario_origen_id",
            "usuario_destino_id", "merchant_id", "tarjeta_id", "fecha_transaccion",
            "tipo_transaccion", "subtipo_transaccion", "monto", "moneda", "canal",
            "estado", "costo_operativo", "ingreso_comision", "riesgo_score",
        ], page_size=500)

        insert_batch(cur, "produccion.fraude", fraude, [
            "fraude_id", "transaccion_id", "fecha_transaccion", "flag_fraude",
            "tipo_alerta", "score_fraude", "modelo_detector",
            "fecha_deteccion", "estado_revision",
        ])

        insert_batch(cur, "produccion.campanas", campanas, [
            "campana_id", "nombre", "tipo", "fecha_inicio", "fecha_fin",
            "segmento_objetivo", "presupuesto", "estado",
        ])

        insert_batch(cur, "produccion.pagos", pagos, [
            "pago_id", "campana_id", "usuario_id",
            "monto_incentivo", "fecha_pago", "estado_pago",
        ])

        insert_batch(cur, "produccion.braze_email_envios", email_envios, [
            "envio_id", "campana_id", "usuario_id",
            "fecha_envio", "template", "estado_entrega",
        ])

        insert_batch(cur, "produccion.braze_whatsapp_envios", wa_envios, [
            "envio_id", "campana_id", "usuario_id",
            "fecha_envio", "template", "estado_entrega",
        ])

        insert_batch(cur, "produccion.braze_email_lectura", email_lect, [
            "lectura_id", "envio_id", "usuario_id", "fecha_lectura", "opened_flag",
        ])

        insert_batch(cur, "produccion.braze_whatsapp_lectura", wa_lect, [
            "lectura_id", "envio_id", "usuario_id", "fecha_lectura", "opened_flag",
        ])

        update_scores_db(cur, usuarios)

        conn.commit()
        logger.info("=== Carga completada exitosamente ===")

    except Exception:
        conn.rollback()
        logger.exception("Error durante la carga — rollback ejecutado.")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
