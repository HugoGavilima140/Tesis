-- ============================================================
--  Schema : transacciones
--  Propósito: Tabla única consolidada que reemplaza la
--             estructura particionada anual de produccion.
--  year_month es columna GENERADA desde fecha_transaccion.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS transacciones;

COMMENT ON SCHEMA transacciones IS
  'Dominio de transacciones financieras. '
  'Reemplaza las tablas transacciones_YYYY de produccion con '
  'una tabla única y columna year_month generada automáticamente.';

-- ============================================================
-- TABLA PRINCIPAL
-- ============================================================
CREATE TABLE IF NOT EXISTS transacciones.transacciones (
    transaccion_id          UUID            NOT NULL DEFAULT gen_random_uuid(),
    transaction_id_origen   BIGINT,

    -- Columna de agrupación temporal, calculada en la aplicación (YYYY-MM)
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
    CONSTRAINT ck_tx_monto
        CHECK (monto <> 0),
    CONSTRAINT ck_tx_estado
        CHECK (estado IN ('completada','pendiente','rechazada','revertida','error')),
    CONSTRAINT ck_tx_canal
        CHECK (canal IN ('chip','banda_magnetica','online','nfc','atm','transferencia','otro')
               OR canal IS NULL),
    CONSTRAINT ck_tx_tipo
        CHECK (tipo_transaccion IN
               ('compra','retiro','transferencia','pago_servicio','recarga','devolucion','ajuste','otro')),
    CONSTRAINT ck_tx_costo
        CHECK (costo_operativo >= 0),
    CONSTRAINT ck_tx_comision
        CHECK (ingreso_comision >= 0),
    CONSTRAINT ck_tx_riesgo
        CHECK (riesgo_score IS NULL OR riesgo_score BETWEEN 0 AND 1)
);

COMMENT ON TABLE  transacciones.transacciones IS
    'Tabla central de transacciones. year_month (YYYY-MM) generada desde fecha_transaccion.';
COMMENT ON COLUMN transacciones.transacciones.year_month IS
    'Calculada en la aplicación: fecha_transaccion.strftime(''%Y-%m''). Siempre en UTC.';
COMMENT ON COLUMN transacciones.transacciones.margen IS
    'Generada: ingreso_comision − costo_operativo.';

-- ============================================================
-- ÍNDICES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_tx_year_month
    ON transacciones.transacciones (year_month);

CREATE INDEX IF NOT EXISTS idx_tx_fecha_desc
    ON transacciones.transacciones (fecha_transaccion DESC);

CREATE INDEX IF NOT EXISTS idx_tx_usuario
    ON transacciones.transacciones (usuario_origen_id);

CREATE INDEX IF NOT EXISTS idx_tx_merchant
    ON transacciones.transacciones (merchant_id);

CREATE INDEX IF NOT EXISTS idx_tx_tarjeta
    ON transacciones.transacciones (tarjeta_id);

CREATE INDEX IF NOT EXISTS idx_tx_estado
    ON transacciones.transacciones (estado);

CREATE INDEX IF NOT EXISTS idx_tx_tipo
    ON transacciones.transacciones (tipo_transaccion);

CREATE INDEX IF NOT EXISTS idx_tx_monto
    ON transacciones.transacciones (monto);

CREATE INDEX IF NOT EXISTS idx_tx_riesgo_alto
    ON transacciones.transacciones (riesgo_score DESC)
    WHERE riesgo_score > 0.5;
