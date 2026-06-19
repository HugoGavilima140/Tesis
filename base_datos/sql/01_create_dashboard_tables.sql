-- ============================================================
--  NUEVO SCHEMA: Tablas necesarias para Dashboard Ejecutivo
--  Payouts, Notificaciones, Integraciones, Account Managers
-- ============================================================

BEGIN;

-- ──────────────────────────────────────────────────────────────
-- 1. Account Managers (Coordinadores)
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS produccion.account_managers (
    manager_id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre              VARCHAR(255)    NOT NULL,
    email               VARCHAR(255)    NOT NULL UNIQUE,
    telefono            VARCHAR(20),
    estado              VARCHAR(20)     NOT NULL DEFAULT 'activo',
    region              VARCHAR(100),
    fecha_contratacion  DATE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_manager_estado CHECK (estado IN ('activo','inactivo','suspendido'))
);

COMMENT ON TABLE produccion.account_managers IS 'Gestores de cuenta (coordinadores) asignados a comercios.';
COMMENT ON COLUMN produccion.account_managers.manager_id IS 'ID único del gestor.';

CREATE INDEX IF NOT EXISTS idx_account_managers_estado ON produccion.account_managers(estado);

-- ──────────────────────────────────────────────────────────────
-- 2. Enriquecer tabla merchants
-- ──────────────────────────────────────────────────────────────
ALTER TABLE produccion.merchants
    ADD COLUMN IF NOT EXISTS cuenta_tipo VARCHAR(50),
    ADD COLUMN IF NOT EXISTS status_operacional VARCHAR(20) DEFAULT 'activo',
    ADD COLUMN IF NOT EXISTS ultima_actividad DATE,
    ADD COLUMN IF NOT EXISTS coordinador_id UUID REFERENCES produccion.account_managers(manager_id);

COMMENT ON COLUMN produccion.merchants.cuenta_tipo IS 'Tipo de cuenta: individual, pyme, empresa.';
COMMENT ON COLUMN produccion.merchants.status_operacional IS 'Estado operativo del comercio.';
COMMENT ON COLUMN produccion.merchants.ultima_actividad IS 'Fecha de última transacción/actividad.';

-- ──────────────────────────────────────────────────────────────
-- 3. Integraciones de Merchants (para Funnel)
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS produccion.integraciones_merchant (
    integracion_id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id             UUID            NOT NULL UNIQUE REFERENCES produccion.merchants(merchant_id),
    estado_integracion      VARCHAR(20)     NOT NULL DEFAULT 'activa',
    email_integrado         BOOLEAN         DEFAULT FALSE,
    sms_integrado           BOOLEAN         DEFAULT FALSE,
    webhook_integrado       BOOLEAN         DEFAULT FALSE,
    api_key_validado        BOOLEAN         DEFAULT FALSE,
    fecha_inicio            DATE            NOT NULL DEFAULT CURRENT_DATE,
    fecha_completacion      DATE,
    coordinador_id          UUID            REFERENCES produccion.account_managers(manager_id),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_integracion_estado CHECK (estado_integracion IN
        ('no_iniciada','en_curso','activa','pausada','suspendida'))
);

COMMENT ON TABLE produccion.integraciones_merchant IS 'Seguimiento de integración de comercios con plataforma.';
COMMENT ON COLUMN produccion.integraciones_merchant.estado_integracion IS 'Estado del onboarding.';

CREATE INDEX IF NOT EXISTS idx_integracion_estado ON produccion.integraciones_merchant(estado_integracion);
CREATE INDEX IF NOT EXISTS idx_integracion_coordinador ON produccion.integraciones_merchant(coordinador_id);

-- ──────────────────────────────────────────────────────────────
-- 4. Payouts (Desembolsos a Comercios)
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS produccion.payouts (
    payout_id               UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id             UUID            NOT NULL REFERENCES produccion.merchants(merchant_id),
    monto                   NUMERIC(15,2)   NOT NULL,
    comision_payout         NUMERIC(12,4)   NOT NULL DEFAULT 0,
    monto_neto              NUMERIC(15,2)   GENERATED ALWAYS AS
                                (monto - comision_payout) STORED,
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'procesado',
    razon_rechazo           VARCHAR(255),
    metodo_pago             VARCHAR(50),
    numero_referencia       VARCHAR(100),
    fecha_solicitud         TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_payout            TIMESTAMPTZ,
    fecha_confirmacion      TIMESTAMPTZ,
    periodo_desde           DATE,
    periodo_hasta           DATE,
    notas                   TEXT,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_payout_monto CHECK (monto > 0),
    CONSTRAINT ck_payout_comision CHECK (comision_payout >= 0),
    CONSTRAINT ck_payout_estado CHECK (estado IN
        ('pendiente','procesado','fallido','rechazado','revertido','pendiente_revision')),
    CONSTRAINT ck_payout_metodo CHECK (metodo_pago IN
        ('transferencia_bancaria','cheque','efectivo','otro') OR metodo_pago IS NULL)
);

COMMENT ON TABLE produccion.payouts IS 'Registro de desembolsos realizados a comercios.';
COMMENT ON COLUMN produccion.payouts.estado IS 'Estado del payout: procesado, pendiente, rechazado, etc.';
COMMENT ON COLUMN produccion.payouts.monto_neto IS 'Monto desembolsado después de comisión (GENERATED).';

CREATE INDEX IF NOT EXISTS idx_payout_merchant ON produccion.payouts(merchant_id);
CREATE INDEX IF NOT EXISTS idx_payout_estado ON produccion.payouts(estado);
CREATE INDEX IF NOT EXISTS idx_payout_fecha ON produccion.payouts(fecha_payout DESC);
CREATE INDEX IF NOT EXISTS idx_payout_merchant_fecha ON produccion.payouts(merchant_id, fecha_payout DESC);

-- ──────────────────────────────────────────────────────────────
-- 5. Notificaciones (Email, SMS, Push)
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS produccion.notificaciones (
    notificacion_id         UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id             UUID            NOT NULL REFERENCES produccion.merchants(merchant_id),
    tipo_canal              VARCHAR(20)     NOT NULL,
    destinatario            VARCHAR(255)    NOT NULL,
    asunto_titulo           VARCHAR(255),
    cantidad_enviada         BIGINT          NOT NULL DEFAULT 1,
    costo_unitario          NUMERIC(8,4)    NOT NULL,
    costo_total             NUMERIC(12,4)   GENERATED ALWAYS AS
                                (cantidad_enviada * costo_unitario) STORED,
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'enviada',
    motivo_fallo            VARCHAR(255),
    tasa_apertura           NUMERIC(5,2),
    tasa_click              NUMERIC(5,2),
    fecha_envio             TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_entrega           TIMESTAMPTZ,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_notif_canal CHECK (tipo_canal IN ('email','sms','push','webhook','whatsapp')),
    CONSTRAINT ck_notif_cantidad CHECK (cantidad_enviada > 0),
    CONSTRAINT ck_notif_costo CHECK (costo_unitario >= 0),
    CONSTRAINT ck_notif_estado CHECK (estado IN
        ('enviada','entregada','fallida','rebotada','spam','no_entregada')),
    CONSTRAINT ck_notif_tasas CHECK (
        (tasa_apertura IS NULL OR (tasa_apertura >= 0 AND tasa_apertura <= 100)) AND
        (tasa_click IS NULL OR (tasa_click >= 0 AND tasa_click <= 100))
    )
);

COMMENT ON TABLE produccion.notificaciones IS 'Registro de notificaciones enviadas a comercios (Email, SMS, Push, etc).';
COMMENT ON COLUMN produccion.notificaciones.tipo_canal IS 'Canal de notificación: email, sms, push, webhook, whatsapp.';
COMMENT ON COLUMN produccion.notificaciones.costo_total IS 'Costo total = cantidad_enviada * costo_unitario (GENERATED).';

CREATE INDEX IF NOT EXISTS idx_notif_merchant ON produccion.notificaciones(merchant_id);
CREATE INDEX IF NOT EXISTS idx_notif_canal ON produccion.notificaciones(tipo_canal);
CREATE INDEX IF NOT EXISTS idx_notif_estado ON produccion.notificaciones(estado);
CREATE INDEX IF NOT EXISTS idx_notif_fecha ON produccion.notificaciones(fecha_envio DESC);
CREATE INDEX IF NOT EXISTS idx_notif_merchant_canal_fecha ON produccion.notificaciones(merchant_id, tipo_canal, fecha_envio DESC);

-- ──────────────────────────────────────────────────────────────
-- 6. Segmentación de Merchants
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS produccion.segmentacion_merchants (
    segmentacion_id         UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id             UUID            NOT NULL UNIQUE REFERENCES produccion.merchants(merchant_id),
    segmento_volumen        VARCHAR(50)     NOT NULL,
    segmento_rentabilidad   VARCHAR(50)     NOT NULL,
    segmento_riesgo         VARCHAR(50),
    mdr_promedio            NUMERIC(6,4),
    valor_promedio_tx       NUMERIC(15,2),
    volumen_anual_estimado  NUMERIC(18,2),
    tasa_rechazo_promedio   NUMERIC(5,2),
    estado_riesgo           VARCHAR(20),
    fecha_segmentacion      DATE            NOT NULL DEFAULT CURRENT_DATE,
    proxima_revision        DATE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT ck_seg_volumen CHECK (segmento_volumen IN ('micro','pequeno','mediano','grande','mega')),
    CONSTRAINT ck_seg_rentabilidad CHECK (segmento_rentabilidad IN ('bronze','silver','gold','platinum','diamond')),
    CONSTRAINT ck_seg_riesgo CHECK (segmento_riesgo IN ('bajo','medio','alto','critico') OR segmento_riesgo IS NULL),
    CONSTRAINT ck_seg_estado_riesgo CHECK (estado_riesgo IN ('monitoreado','normal','alerta','suspendido') OR estado_riesgo IS NULL)
);

COMMENT ON TABLE produccion.segmentacion_merchants IS 'Clasificación y segmentación de comercios para análisis y decisiones estratégicas.';
COMMENT ON COLUMN produccion.segmentacion_merchants.segmento_volumen IS 'Segmento por volumen de transacciones: micro, pequeño, mediano, grande, mega.';

CREATE INDEX IF NOT EXISTS idx_seg_merchant_volumen ON produccion.segmentacion_merchants(merchant_id, segmento_volumen);
CREATE INDEX IF NOT EXISTS idx_seg_rentabilidad ON produccion.segmentacion_merchants(segmento_rentabilidad);

-- ──────────────────────────────────────────────────────────────
-- 7. Enriquecer tabla transacciones (si no existen ya las columnas)
-- ──────────────────────────────────────────────────────────────
ALTER TABLE transacciones.transacciones
    ADD COLUMN IF NOT EXISTS razon_rechazo VARCHAR(100),
    ADD COLUMN IF NOT EXISTS hora_transaccion SMALLINT,
    ADD COLUMN IF NOT EXISTS dia_semana SMALLINT,
    ADD COLUMN IF NOT EXISTS mes INT;

-- Generar valores para columnas derivadas
UPDATE transacciones.transacciones
SET
    hora_transaccion = EXTRACT(HOUR FROM fecha_transaccion)::SMALLINT,
    dia_semana = EXTRACT(DOW FROM fecha_transaccion)::SMALLINT,
    mes = EXTRACT(MONTH FROM fecha_transaccion)::INT
WHERE hora_transaccion IS NULL;

CREATE INDEX IF NOT EXISTS idx_tx_hora ON transacciones.transacciones(hora_transaccion);
CREATE INDEX IF NOT EXISTS idx_tx_dia_semana ON transacciones.transacciones(dia_semana);

-- ──────────────────────────────────────────────────────────────
-- 8. Vistas Materializadas para Dashboard
-- ──────────────────────────────────────────────────────────────

-- Vista: Métricas diarias por merchant
CREATE MATERIALIZED VIEW IF NOT EXISTS produccion.mv_metricas_diarias AS
SELECT
    DATE(t.fecha_transaccion) AS fecha,
    t.merchant_id,
    m.nombre_comercio,
    COUNT(t.transaccion_id) AS total_transacciones,
    SUM(CASE WHEN t.estado = 'completada' THEN 1 ELSE 0 END) AS transacciones_completadas,
    SUM(CASE WHEN t.estado IN ('rechazada','error','revertida') THEN 1 ELSE 0 END) AS transacciones_rechazadas,
    SUM(t.monto) AS gmv,
    SUM(t.ingreso_comision) AS mdr,
    SUM(t.costo_operativo) AS costos_operativos,
    SUM(t.margen) AS margen_neto,
    AVG(t.monto) AS ticket_promedio,
    COUNT(CASE WHEN f.flag_fraude THEN 1 END) AS transacciones_fraude,
    ROUND(COUNT(CASE WHEN t.estado = 'completada' THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) AS tasa_exito,
    NOW() AS created_at
FROM transacciones.transacciones t
LEFT JOIN produccion.merchants m ON t.merchant_id = m.merchant_id
LEFT JOIN produccion.fraude f ON t.transaccion_id = f.transaccion_id
GROUP BY DATE(t.fecha_transaccion), t.merchant_id, m.nombre_comercio;

CREATE INDEX IF NOT EXISTS idx_mv_metricas_fecha ON produccion.mv_metricas_diarias(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_mv_metricas_merchant ON produccion.mv_metricas_diarias(merchant_id);

-- ──────────────────────────────────────────────────────────────
-- 9. Vistas para Dashboard
-- ──────────────────────────────────────────────────────────────

-- Funnel operativo
CREATE OR REPLACE VIEW produccion.vw_funnel_comercios AS
SELECT
    COUNT(DISTINCT m.merchant_id) AS comercios_registrados,
    COUNT(DISTINCT CASE WHEN i.estado_integracion = 'activa' THEN m.merchant_id END) AS comercios_integrados,
    COUNT(DISTINCT CASE WHEN m.ultima_actividad >= CURRENT_DATE - INTERVAL '30 days' THEN m.merchant_id END) AS comercios_activos,
    COUNT(DISTINCT CASE WHEN i.email_integrado OR i.sms_integrado THEN m.merchant_id END) AS comercios_con_notificaciones,
    COUNT(DISTINCT t.merchant_id) AS comercios_con_transacciones,
    COUNT(DISTINCT p.merchant_id) AS comercios_con_payouts,
    ROUND(COUNT(DISTINCT CASE WHEN i.estado_integracion = 'activa' THEN m.merchant_id END)::NUMERIC /
        NULLIF(COUNT(DISTINCT m.merchant_id), 0) * 100, 2) AS porcentaje_integracion,
    ROUND(COUNT(DISTINCT CASE WHEN m.ultima_actividad >= CURRENT_DATE - INTERVAL '30 days' THEN m.merchant_id END)::NUMERIC /
        NULLIF(COUNT(DISTINCT m.merchant_id), 0) * 100, 2) AS porcentaje_activos
FROM produccion.merchants m
LEFT JOIN produccion.integraciones_merchant i ON m.merchant_id = i.merchant_id
LEFT JOIN transacciones.transacciones t ON m.merchant_id = t.merchant_id AND t.estado = 'completada'
LEFT JOIN produccion.payouts p ON m.merchant_id = p.merchant_id AND p.estado = 'procesado'
WHERE m.status_operacional = 'activo';

-- Matriz comercios estratégicos
CREATE OR REPLACE VIEW produccion.vw_matriz_comercios_estrategicos AS
SELECT
    m.merchant_id,
    m.nombre_comercio,
    m.categoria,
    SUM(t.monto) AS gmv_total,
    COUNT(t.transaccion_id) AS total_transacciones,
    AVG(t.margen) AS rentabilidad_promedio,
    SUM(n.costo_total) AS costo_notificaciones_total,
    s.segmento_rentabilidad,
    s.segmento_volumen,
    COUNT(t.transaccion_id) AS size_bubble,
    SUM(n.costo_total) AS color_value
FROM produccion.merchants m
LEFT JOIN transacciones.transacciones t ON m.merchant_id = t.merchant_id AND t.estado = 'completada'
LEFT JOIN produccion.notificaciones n ON m.merchant_id = n.merchant_id
LEFT JOIN produccion.segmentacion_merchants s ON m.merchant_id = s.merchant_id
WHERE m.status_operacional = 'activo'
GROUP BY m.merchant_id, m.nombre_comercio, m.categoria, s.segmento_rentabilidad, s.segmento_volumen;

-- Waterfall rentabilidad
CREATE OR REPLACE VIEW produccion.vw_waterfall_rentabilidad AS
SELECT
    DATE(t.fecha_transaccion) AS fecha,
    SUM(t.monto) AS gmv,
    SUM(t.ingreso_comision) AS mdr,
    SUM(n.costo_total) AS costo_notificaciones,
    SUM(t.costo_operativo) AS otros_costos,
    SUM(t.margen) - SUM(n.costo_total) AS margen_neto
FROM transacciones.transacciones t
LEFT JOIN produccion.notificaciones n ON DATE(t.fecha_transaccion) = DATE(n.fecha_envio)
WHERE t.estado = 'completada'
GROUP BY DATE(t.fecha_transaccion);

-- KPI Dashboard
CREATE OR REPLACE VIEW produccion.vw_kpi_dashboard AS
SELECT
    SUM(t.monto) AS gmv_total,
    COUNT(t.transaccion_id) AS total_transacciones,
    COUNT(DISTINCT p.payout_id) AS total_payouts,
    SUM(t.ingreso_comision) AS mdr_total,
    AVG(t.monto) AS ticket_promedio,
    ROUND(COUNT(CASE WHEN t.estado = 'completada' THEN 1 END)::NUMERIC /
        NULLIF(COUNT(t.transaccion_id), 0) * 100, 2) AS tasa_exito_general,
    SUM(n.costo_total) AS costo_notificaciones_total,
    COUNT(DISTINCT t.usuario_origen_id) AS usuarios_activos,
    COUNT(DISTINCT t.merchant_id) AS merchants_activos
FROM transacciones.transacciones t
LEFT JOIN produccion.payouts p ON DATE(p.fecha_payout) >= DATE(t.fecha_transaccion) - INTERVAL '30 days'
LEFT JOIN produccion.notificaciones n ON DATE(n.fecha_envio) >= DATE(t.fecha_transaccion) - INTERVAL '30 days';

-- ──────────────────────────────────────────────────────────────
-- 10. Registrar migración
-- ──────────────────────────────────────────────────────────────
INSERT INTO produccion.schema_migrations (version, nombre, checksum)
VALUES (
    '1.2.0',
    'create_dashboard_tables_payouts_notificaciones_integraciones',
    md5('create_dashboard_tables_v1_2_0')
)
ON CONFLICT (version) DO NOTHING;

COMMIT;
