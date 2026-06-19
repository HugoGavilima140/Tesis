-- ============================================================
--  FINTECH DB  ·  IBM Financial Transaction Dataset
--  Motor   : PostgreSQL 13+
--  Schema  : produccion
--  Versión : 1.0.0
--  Autor   : Arquitectura de datos – Tesis IA
-- ============================================================

-- ============================================================
-- EXTENSIONES
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";       -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";      -- uuid_generate_v4() fallback
CREATE EXTENSION IF NOT EXISTS "pg_trgm";        -- búsquedas de texto eficientes

-- ============================================================
-- SCHEMA PRINCIPAL
-- ============================================================
CREATE SCHEMA IF NOT EXISTS produccion;

COMMENT ON SCHEMA produccion IS
  'Schema principal del ecosistema fintech. '
  'Subdominios: clientes, productos, transacciones, campañas. '
  'Fuente primaria: IBM Financial Transaction Dataset.';

-- ============================================================
-- FUNCIÓN AUDIT  –  updated_at automático
-- ============================================================
CREATE OR REPLACE FUNCTION produccion.fn_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

-- ============================================================
-- ██████████  DOMINIO: CLIENTES  ██████████
-- ============================================================

-- ----------------------------------------------------------
-- 1. usuarios
--    Origen IBM: columna [User]
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.usuarios (
    usuario_id              UUID            NOT NULL DEFAULT gen_random_uuid(),
    customer_id_origen      BIGINT          NOT NULL,       -- IBM [User]
    fecha_registro          DATE,                           -- MIN(fecha_tx) por usuario
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'activo',
    tipo_usuario            VARCHAR(30)     NOT NULL DEFAULT 'individual',
    nivel_riesgo            VARCHAR(20)     NOT NULL DEFAULT 'medio',
    pais                    CHAR(3),                        -- 'USA' para IBM dataset
    ciudad                  VARCHAR(100),                   -- ciudad más frecuente del usuario
    score_actividad         NUMERIC(5,2),                   -- log1p(n_tx) norm. 0-100
    score_rentabilidad      NUMERIC(5,2),                   -- vol_total norm. 0-100
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_usuarios
        PRIMARY KEY (usuario_id),
    CONSTRAINT uq_usuarios_customer_id
        UNIQUE (customer_id_origen),
    CONSTRAINT ck_usuarios_estado
        CHECK (estado IN ('activo','inactivo','suspendido','bloqueado')),
    CONSTRAINT ck_usuarios_tipo
        CHECK (tipo_usuario IN ('individual','empresarial','premium','basico')),
    CONSTRAINT ck_usuarios_riesgo
        CHECK (nivel_riesgo IN ('bajo','medio','alto','critico')),
    CONSTRAINT ck_usuarios_score_act
        CHECK (score_actividad IS NULL OR score_actividad BETWEEN 0 AND 100),
    CONSTRAINT ck_usuarios_score_rent
        CHECK (score_rentabilidad IS NULL OR score_rentabilidad BETWEEN 0 AND 100)
);

COMMENT ON TABLE  produccion.usuarios                       IS 'Tabla maestra de clientes. IBM fuente: [User].';
COMMENT ON COLUMN produccion.usuarios.customer_id_origen    IS 'IBM [User]: ID numérico 0-N del cliente.';
COMMENT ON COLUMN produccion.usuarios.fecha_registro        IS 'Derivado: MIN(fecha_transaccion) agrupado por User.';
COMMENT ON COLUMN produccion.usuarios.nivel_riesgo          IS 'Derivado: pct_fraude<1%→bajo, <5%→medio, <15%→alto, ≥15%→critico.';
COMMENT ON COLUMN produccion.usuarios.score_actividad       IS 'ETL: LN(1+count_tx) normalizado 0-100.';
COMMENT ON COLUMN produccion.usuarios.score_rentabilidad    IS 'ETL: SUM(monto) / MAX(SUM(monto)) * 100.';

-- ----------------------------------------------------------
-- 2. dispositivos
--    Sin equivalente directo en IBM → datos sintéticos
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.dispositivos (
    dispositivo_id          UUID            NOT NULL DEFAULT gen_random_uuid(),
    usuario_id              UUID            NOT NULL,
    device_type             VARCHAR(50),                    -- 'mobile','tablet','desktop'
    sistema_operativo       VARCHAR(50),                    -- 'iOS','Android','Web'
    version_app             VARCHAR(20),
    fecha_primer_uso        DATE,
    fecha_ultimo_uso        DATE,
    estado_dispositivo      VARCHAR(20)     NOT NULL DEFAULT 'activo',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_dispositivos
        PRIMARY KEY (dispositivo_id),
    CONSTRAINT fk_dispositivos_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_dispositivos_estado
        CHECK (estado_dispositivo IN ('activo','inactivo','bloqueado','eliminado'))
);

COMMENT ON TABLE produccion.dispositivos IS 'Dispositivos del usuario. Datos sintéticos: IBM no provee este campo.';

-- ----------------------------------------------------------
-- 3. merchants
--    Origen IBM: [Merchant Name], [Merchant City],
--                [Merchant State], [Zip], [MCC]
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.merchants (
    merchant_id             UUID            NOT NULL DEFAULT gen_random_uuid(),
    merchant_id_origen      BIGINT,                         -- IBM [Merchant Name] (ID numérico)
    nombre_comercio         VARCHAR(255),                   -- cast a texto o alias
    categoria               VARCHAR(100),                   -- derivado de MCC
    mcc_code                SMALLINT,                       -- IBM [MCC]
    segmento                VARCHAR(100),                   -- derivado de rango MCC
    ciudad                  VARCHAR(100),                   -- IBM [Merchant City]
    estado_region           VARCHAR(10),                    -- IBM [Merchant State]
    zip_code                VARCHAR(10),                    -- IBM [Zip]
    pais                    CHAR(3)         NOT NULL DEFAULT 'USA',
    fecha_afiliacion        DATE,                           -- sintético: 2018-01-01 por defecto
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'activo',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_merchants
        PRIMARY KEY (merchant_id),
    CONSTRAINT uq_merchants_origen
        UNIQUE (merchant_id_origen),
    CONSTRAINT ck_merchants_estado
        CHECK (estado IN ('activo','inactivo','suspendido'))
);

COMMENT ON TABLE  produccion.merchants                  IS 'Comercios afiliados. IBM fuente: [Merchant Name], [Merchant City], [Merchant State], [MCC].';
COMMENT ON COLUMN produccion.merchants.merchant_id_origen IS 'IBM [Merchant Name]: valor numérico del dataset.';
COMMENT ON COLUMN produccion.merchants.mcc_code           IS 'IBM [MCC]: Merchant Category Code (ISO 18245).';
COMMENT ON COLUMN produccion.merchants.categoria          IS 'Derivado de MCC: lookup table interna del ETL.';
COMMENT ON COLUMN produccion.merchants.segmento           IS 'Derivado de rango MCC: Retail, Gastronomía, Salud, etc.';

-- ----------------------------------------------------------
-- 4. usuarios_demographics
--    Sin equivalente en IBM → schema creado, datos nulos/sintéticos
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.usuarios_demographics (
    usuario_id              UUID            NOT NULL,
    rango_edad              VARCHAR(20),                    -- '18-25','26-35','36-50','51+'
    genero                  CHAR(1)         CHECK (genero IN ('M','F','O') OR genero IS NULL),
    ocupacion               VARCHAR(100),
    nivel_ingresos_estimado VARCHAR(30),                    -- 'bajo','medio_bajo','medio','medio_alto','alto'
    antiguedad_cliente      SMALLINT        CHECK (antiguedad_cliente IS NULL OR antiguedad_cliente >= 0),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_usuarios_demographics
        PRIMARY KEY (usuario_id),
    CONSTRAINT fk_demographics_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_demographics_ingresos
        CHECK (nivel_ingresos_estimado IN ('bajo','medio_bajo','medio','medio_alto','alto') OR nivel_ingresos_estimado IS NULL)
);

COMMENT ON TABLE produccion.usuarios_demographics IS 'Datos demográficos. IBM no provee este campo: tabla creada para extensibilidad futura.';

-- ----------------------------------------------------------
-- 5. segmentacion
--    Calculado mediante ETL / modelo ML
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.segmentacion (
    segmentacion_id         UUID            NOT NULL DEFAULT gen_random_uuid(),
    usuario_id              UUID            NOT NULL,
    segmento_transaccional  VARCHAR(50),    -- 'alto_volumen','frecuente','esporadico','inactivo'
    segmento_rentabilidad   VARCHAR(50),    -- 'platinum','gold','silver','bronze'
    segmento_riesgo         VARCHAR(50),    -- 'critico','alto','medio','bajo'
    cluster_ml              SMALLINT,       -- resultado K-Means u otro algoritmo
    fecha_segmentacion      DATE            NOT NULL DEFAULT CURRENT_DATE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_segmentacion
        PRIMARY KEY (segmentacion_id),
    CONSTRAINT fk_segmentacion_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT uq_segmentacion_usuario_fecha
        UNIQUE (usuario_id, fecha_segmentacion)
);

COMMENT ON TABLE  produccion.segmentacion                     IS 'Segmentación multidimensional, recalculada periódicamente por ETL.';
COMMENT ON COLUMN produccion.segmentacion.cluster_ml          IS 'Cluster asignado por modelo ML. NULL si aún no ejecutado.';
COMMENT ON COLUMN produccion.segmentacion.fecha_segmentacion  IS 'Permite histórico de cambios de segmento por usuario.';

-- ============================================================
-- ██████████  DOMINIO: PRODUCTOS  ██████████
-- ============================================================

-- ----------------------------------------------------------
-- 6. tarjetas
--    Origen IBM: [Card] (número), [Use Chip] (tipo)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.tarjetas (
    tarjeta_id              UUID            NOT NULL DEFAULT gen_random_uuid(),
    card_id_origen          BIGINT,                         -- IBM [Card]
    usuario_id              UUID            NOT NULL,
    tipo_tarjeta            VARCHAR(30)     NOT NULL DEFAULT 'debito',
    marca                   VARCHAR(30),                    -- sintético: Visa/Mastercard/Amex/Discover
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'activa',
    fecha_emision           DATE,                           -- MIN(fecha_tx) por tarjeta
    limite_credito          NUMERIC(15,2)   CHECK (limite_credito IS NULL OR limite_credito >= 0),
    score_uso               NUMERIC(5,2)    CHECK (score_uso IS NULL OR score_uso BETWEEN 0 AND 100),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_tarjetas
        PRIMARY KEY (tarjeta_id),
    CONSTRAINT uq_tarjetas_card_usuario
        UNIQUE (card_id_origen, usuario_id),
    CONSTRAINT fk_tarjetas_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT ck_tarjetas_tipo
        CHECK (tipo_tarjeta IN ('debito','credito','prepago','virtual')),
    CONSTRAINT ck_tarjetas_estado
        CHECK (estado IN ('activa','inactiva','bloqueada','vencida','cancelada'))
);

COMMENT ON TABLE  produccion.tarjetas               IS 'Tarjetas de pago. IBM fuente: [Card], [Use Chip].';
COMMENT ON COLUMN produccion.tarjetas.card_id_origen IS 'IBM [Card]: número de tarjeta (entero en el dataset).';
COMMENT ON COLUMN produccion.tarjetas.tipo_tarjeta   IS 'Derivado [Use Chip]: Chip/Swipe→débito, Online→virtual.';
COMMENT ON COLUMN produccion.tarjetas.fecha_emision  IS 'Derivado: MIN(fecha_transaccion) para cada card+usuario.';

-- ----------------------------------------------------------
-- 7. aplicacion
--    Sin equivalente en IBM → datos sintéticos
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.aplicacion (
    app_id                  UUID            NOT NULL DEFAULT gen_random_uuid(),
    usuario_id              UUID            NOT NULL,
    version                 VARCHAR(20),
    canal_adquisicion       VARCHAR(50),
    fecha_activacion        DATE,
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'activa',
    engagement_score        NUMERIC(5,2)    CHECK (engagement_score IS NULL OR engagement_score BETWEEN 0 AND 100),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_aplicacion
        PRIMARY KEY (app_id),
    CONSTRAINT fk_aplicacion_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT ck_aplicacion_estado
        CHECK (estado IN ('activa','inactiva','desinstalada')),
    CONSTRAINT ck_aplicacion_canal
        CHECK (canal_adquisicion IN ('organic','paid_search','social_media','referral','email','otro') OR canal_adquisicion IS NULL)
);

COMMENT ON TABLE produccion.aplicacion IS 'App móvil por usuario. Datos sintéticos: IBM no provee información de app.';

-- ============================================================
-- ██████████  DOMINIO: TRANSACCIONES  ██████████
-- ============================================================

-- ----------------------------------------------------------
-- 8. transacciones  (tabla central – particionada por fecha)
--    Origen IBM: prácticamente todas las columnas del dataset
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.transacciones (
    transaccion_id          UUID            NOT NULL DEFAULT gen_random_uuid(),
    transaction_id_origen   BIGINT,                         -- índice de fila IBM
    usuario_origen_id       UUID            NOT NULL,       -- IBM [User]
    usuario_destino_id      UUID,                           -- NULL para compras
    merchant_id             UUID,                           -- IBM [Merchant Name]
    tarjeta_id              UUID,                           -- IBM [Card]
    fecha_transaccion       TIMESTAMPTZ     NOT NULL,       -- IBM Year+Month+Day+Time
    tipo_transaccion        VARCHAR(50)     NOT NULL,       -- derivado de MCC
    subtipo_transaccion     VARCHAR(100),                   -- categoría MCC detallada
    monto                   NUMERIC(15,2)   NOT NULL,       -- IBM [Amount] (limpiado)
    moneda                  CHAR(3)         NOT NULL DEFAULT 'USD',
    canal                   VARCHAR(30),                    -- IBM [Use Chip] mapeado
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'completada',
    costo_operativo         NUMERIC(12,4)   NOT NULL DEFAULT 0,   -- 0.8 % del monto
    ingreso_comision        NUMERIC(12,4)   NOT NULL DEFAULT 0,   -- 1.8 % del monto
    margen                  NUMERIC(12,4)   GENERATED ALWAYS AS
                                (ingreso_comision - costo_operativo) STORED,
    riesgo_score            NUMERIC(6,4)    CHECK (riesgo_score IS NULL OR riesgo_score BETWEEN 0 AND 1),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_transacciones
        PRIMARY KEY (transaccion_id, fecha_transaccion),   -- PK compuesta requerida por partición
    CONSTRAINT uq_transacciones_origen
        UNIQUE (transaction_id_origen, fecha_transaccion),
    CONSTRAINT fk_tx_usuario_origen
        FOREIGN KEY (usuario_origen_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tx_usuario_destino
        FOREIGN KEY (usuario_destino_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_tx_merchant
        FOREIGN KEY (merchant_id)
        REFERENCES produccion.merchants (merchant_id)
        ON DELETE SET NULL,
    CONSTRAINT fk_tx_tarjeta
        FOREIGN KEY (tarjeta_id)
        REFERENCES produccion.tarjetas (tarjeta_id)
        ON DELETE SET NULL,
    CONSTRAINT ck_tx_monto
        CHECK (monto <> 0),
    CONSTRAINT ck_tx_estado
        CHECK (estado IN ('completada','pendiente','rechazada','revertida','error')),
    CONSTRAINT ck_tx_canal
        CHECK (canal IN ('chip','banda_magnetica','online','nfc','atm','transferencia','otro') OR canal IS NULL),
    CONSTRAINT ck_tx_tipo
        CHECK (tipo_transaccion IN ('compra','retiro','transferencia','pago_servicio','recarga','devolucion','ajuste','otro')),
    CONSTRAINT ck_tx_costo
        CHECK (costo_operativo >= 0),
    CONSTRAINT ck_tx_comision
        CHECK (ingreso_comision >= 0)

) PARTITION BY RANGE (fecha_transaccion);

COMMENT ON TABLE  produccion.transacciones                    IS 'Tabla central de transacciones. Particionada por año. IBM fuente: todas las columnas principales.';
COMMENT ON COLUMN produccion.transacciones.transaction_id_origen IS 'Índice (0-based) de la fila original en el CSV del IBM Dataset.';
COMMENT ON COLUMN produccion.transacciones.monto              IS 'IBM [Amount]: limpiado ($ removido, negativo respetado).';
COMMENT ON COLUMN produccion.transacciones.canal              IS 'IBM [Use Chip]: Chip→chip, Swipe→banda_magnetica, Online→online.';
COMMENT ON COLUMN produccion.transacciones.estado             IS 'IBM [Errors?]: vacío→completada, error específico→rechazada/error.';
COMMENT ON COLUMN produccion.transacciones.riesgo_score       IS 'IBM [Is Fraud?]: Yes→0.95, No→0.05 (ajustable con modelo propio).';
COMMENT ON COLUMN produccion.transacciones.margen             IS 'Columna generada: ingreso_comision − costo_operativo.';

-- Particiones anuales (IBM dataset cubre aprox. 2010-2019)
CREATE TABLE IF NOT EXISTS produccion.transacciones_2010
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2010-01-01') TO ('2011-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2011
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2011-01-01') TO ('2012-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2012
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2012-01-01') TO ('2013-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2013
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2013-01-01') TO ('2014-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2014
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2014-01-01') TO ('2015-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2015
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2015-01-01') TO ('2016-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2016
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2016-01-01') TO ('2017-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2017
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2017-01-01') TO ('2018-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2018
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2018-01-01') TO ('2019-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2019
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_2020
    PARTITION OF produccion.transacciones
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');

CREATE TABLE IF NOT EXISTS produccion.transacciones_default
    PARTITION OF produccion.transacciones
    DEFAULT;

-- ----------------------------------------------------------
-- 9. fraude
--    Origen IBM: [Is Fraud?]
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.fraude (
    fraude_id               UUID            NOT NULL DEFAULT gen_random_uuid(),
    transaccion_id          UUID            NOT NULL,
    fecha_transaccion       TIMESTAMPTZ     NOT NULL,       -- necesario por partición
    flag_fraude             BOOLEAN         NOT NULL DEFAULT FALSE,
    tipo_alerta             VARCHAR(50),
    score_fraude            NUMERIC(6,4)    CHECK (score_fraude IS NULL OR score_fraude BETWEEN 0 AND 1),
    modelo_detector         VARCHAR(100),
    fecha_deteccion         TIMESTAMPTZ,
    estado_revision         VARCHAR(30)     NOT NULL DEFAULT 'pendiente',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_fraude
        PRIMARY KEY (fraude_id),
    CONSTRAINT fk_fraude_transaccion
        FOREIGN KEY (transaccion_id, fecha_transaccion)
        REFERENCES produccion.transacciones (transaccion_id, fecha_transaccion)
        ON DELETE CASCADE,
    CONSTRAINT ck_fraude_estado
        CHECK (estado_revision IN ('pendiente','en_revision','confirmado','descartado','escalado')),
    CONSTRAINT ck_fraude_tipo
        CHECK (tipo_alerta IN (
            'monto_inusual','ubicacion_anomala','frecuencia_alta',
            'patron_sospechoso','tarjeta_clonada','identidad_robada','otro'
        ) OR tipo_alerta IS NULL)
);

COMMENT ON TABLE  produccion.fraude               IS 'Alertas de fraude. IBM fuente: [Is Fraud?].';
COMMENT ON COLUMN produccion.fraude.flag_fraude   IS 'IBM [Is Fraud?]: Yes=TRUE, No=FALSE.';
COMMENT ON COLUMN produccion.fraude.tipo_alerta   IS 'Sintético: generado aleatoriamente para filas con flag_fraude=TRUE.';
COMMENT ON COLUMN produccion.fraude.modelo_detector IS '"IBM_Label_v1" en carga inicial; sustituible por modelo propio.';

-- ============================================================
-- ██████████  DOMINIO: CAMPAÑAS  ██████████
-- ============================================================

-- ----------------------------------------------------------
-- 10. campanas
--     Sin equivalente en IBM → datos completamente sintéticos
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.campanas (
    campana_id              UUID            NOT NULL DEFAULT gen_random_uuid(),
    nombre                  VARCHAR(255)    NOT NULL,
    tipo                    VARCHAR(50)     NOT NULL,
    fecha_inicio            DATE,
    fecha_fin               DATE,
    segmento_objetivo       VARCHAR(100),   -- ref. a segmentacion.segmento_transaccional
    presupuesto             NUMERIC(15,2)   CHECK (presupuesto IS NULL OR presupuesto >= 0),
    estado                  VARCHAR(20)     NOT NULL DEFAULT 'planificada',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_campanas
        PRIMARY KEY (campana_id),
    CONSTRAINT ck_campanas_tipo
        CHECK (tipo IN ('email','whatsapp','push','sms','mixta','inapp')),
    CONSTRAINT ck_campanas_estado
        CHECK (estado IN ('planificada','activa','pausada','finalizada','cancelada')),
    CONSTRAINT ck_campanas_fechas
        CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio)
);

COMMENT ON TABLE produccion.campanas IS 'Campañas de marketing. Datos sintéticos: IBM no contiene información de campañas.';

-- ----------------------------------------------------------
-- 11. pagos  (incentivos de campañas a usuarios)
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.pagos (
    pago_id                 UUID            NOT NULL DEFAULT gen_random_uuid(),
    campana_id              UUID            NOT NULL,
    usuario_id              UUID            NOT NULL,
    monto_incentivo         NUMERIC(10,2)   NOT NULL CHECK (monto_incentivo >= 0),
    fecha_pago              DATE,
    estado_pago             VARCHAR(20)     NOT NULL DEFAULT 'pendiente',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_pagos
        PRIMARY KEY (pago_id),
    CONSTRAINT fk_pagos_campana
        FOREIGN KEY (campana_id)
        REFERENCES produccion.campanas (campana_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_pagos_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_pagos_estado
        CHECK (estado_pago IN ('pendiente','procesado','fallido','revertido'))
);

-- ----------------------------------------------------------
-- 12. braze_email_envios
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.braze_email_envios (
    envio_id                UUID            NOT NULL DEFAULT gen_random_uuid(),
    campana_id              UUID            NOT NULL,
    usuario_id              UUID            NOT NULL,
    fecha_envio             TIMESTAMPTZ,
    template                VARCHAR(100),
    estado_entrega          VARCHAR(30)     NOT NULL DEFAULT 'enviado',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_braze_email_envios
        PRIMARY KEY (envio_id),
    CONSTRAINT fk_braze_email_env_campana
        FOREIGN KEY (campana_id)
        REFERENCES produccion.campanas (campana_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_braze_email_env_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE,
    CONSTRAINT ck_braze_email_env_estado
        CHECK (estado_entrega IN ('enviado','entregado','rebotado','bloqueado','fallido'))
);

-- ----------------------------------------------------------
-- 13. braze_whatsapp_envios
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.braze_whatsapp_envios (
    envio_id                UUID            NOT NULL DEFAULT gen_random_uuid(),
    campana_id              UUID            NOT NULL,
    usuario_id              UUID            NOT NULL,
    fecha_envio             TIMESTAMPTZ,
    template                VARCHAR(100),
    estado_entrega          VARCHAR(30)     NOT NULL DEFAULT 'enviado',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_braze_wa_envios
        PRIMARY KEY (envio_id),
    CONSTRAINT fk_braze_wa_env_campana
        FOREIGN KEY (campana_id)
        REFERENCES produccion.campanas (campana_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_braze_wa_env_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE,
    CONSTRAINT ck_braze_wa_env_estado
        CHECK (estado_entrega IN ('enviado','entregado','leido','fallido','bloqueado'))
);

-- ----------------------------------------------------------
-- 14. braze_email_lectura
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.braze_email_lectura (
    lectura_id              UUID            NOT NULL DEFAULT gen_random_uuid(),
    envio_id                UUID            NOT NULL,
    usuario_id              UUID            NOT NULL,
    fecha_lectura           TIMESTAMPTZ,
    opened_flag             BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_braze_email_lectura
        PRIMARY KEY (lectura_id),
    CONSTRAINT fk_braze_email_lect_envio
        FOREIGN KEY (envio_id)
        REFERENCES produccion.braze_email_envios (envio_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_braze_email_lect_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_braze_email_lectura_envio_usr
        UNIQUE (envio_id, usuario_id)
);

-- ----------------------------------------------------------
-- 15. braze_whatsapp_lectura
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS produccion.braze_whatsapp_lectura (
    lectura_id              UUID            NOT NULL DEFAULT gen_random_uuid(),
    envio_id                UUID            NOT NULL,
    usuario_id              UUID            NOT NULL,
    fecha_lectura           TIMESTAMPTZ,
    opened_flag             BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_braze_wa_lectura
        PRIMARY KEY (lectura_id),
    CONSTRAINT fk_braze_wa_lect_envio
        FOREIGN KEY (envio_id)
        REFERENCES produccion.braze_whatsapp_envios (envio_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_braze_wa_lect_usuario
        FOREIGN KEY (usuario_id)
        REFERENCES produccion.usuarios (usuario_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_braze_wa_lectura_envio_usr
        UNIQUE (envio_id, usuario_id)
);

-- ============================================================
-- ██████████  INFRAESTRUCTURA ETL  ██████████
-- ============================================================

CREATE TABLE IF NOT EXISTS produccion.etl_control (
    control_id              SERIAL          PRIMARY KEY,
    nombre_proceso          VARCHAR(100)    NOT NULL,
    ultima_ejecucion        TIMESTAMPTZ,
    ultimo_id_procesado     BIGINT,
    ultima_fecha_procesada  TIMESTAMPTZ,
    registros_procesados    INTEGER         DEFAULT 0,
    estado_ultimo_proceso   VARCHAR(20)     DEFAULT 'pendiente',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_etl_proceso UNIQUE (nombre_proceso),
    CONSTRAINT ck_etl_estado CHECK (
        estado_ultimo_proceso IN ('pendiente','en_proceso','exitoso','fallido')
    )
);

CREATE TABLE IF NOT EXISTS produccion.schema_migrations (
    migration_id            SERIAL          PRIMARY KEY,
    version                 VARCHAR(20)     NOT NULL,
    nombre                  VARCHAR(255)    NOT NULL,
    aplicada_en             TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum                VARCHAR(64),
    ejecutada_por           VARCHAR(100)    DEFAULT CURRENT_USER,

    CONSTRAINT uq_migrations_version UNIQUE (version)
);

-- ============================================================
-- ██████████  INDEXES  ██████████
-- ============================================================

-- usuarios
CREATE INDEX IF NOT EXISTS idx_usuarios_estado
    ON produccion.usuarios (estado)
    WHERE estado <> 'bloqueado';

CREATE INDEX IF NOT EXISTS idx_usuarios_pais_ciudad
    ON produccion.usuarios (pais, ciudad);

CREATE INDEX IF NOT EXISTS idx_usuarios_nivel_riesgo
    ON produccion.usuarios (nivel_riesgo);

CREATE INDEX IF NOT EXISTS idx_usuarios_scores
    ON produccion.usuarios (score_actividad DESC, score_rentabilidad DESC);

-- merchants
CREATE INDEX IF NOT EXISTS idx_merchants_mcc
    ON produccion.merchants (mcc_code);

CREATE INDEX IF NOT EXISTS idx_merchants_ciudad_pais
    ON produccion.merchants (ciudad, pais);

CREATE INDEX IF NOT EXISTS idx_merchants_categoria
    ON produccion.merchants (categoria);

CREATE INDEX IF NOT EXISTS idx_merchants_nombre_trgm
    ON produccion.merchants USING GIN (nombre_comercio gin_trgm_ops);

-- tarjetas
CREATE INDEX IF NOT EXISTS idx_tarjetas_usuario
    ON produccion.tarjetas (usuario_id);

CREATE INDEX IF NOT EXISTS idx_tarjetas_estado
    ON produccion.tarjetas (estado)
    WHERE estado = 'activa';

-- transacciones (índices se propagan a todas las particiones)
CREATE INDEX IF NOT EXISTS idx_tx_usuario_origen
    ON produccion.transacciones (usuario_origen_id);

CREATE INDEX IF NOT EXISTS idx_tx_merchant
    ON produccion.transacciones (merchant_id);

CREATE INDEX IF NOT EXISTS idx_tx_tarjeta
    ON produccion.transacciones (tarjeta_id);

CREATE INDEX IF NOT EXISTS idx_tx_fecha_desc
    ON produccion.transacciones (fecha_transaccion DESC);

CREATE INDEX IF NOT EXISTS idx_tx_estado
    ON produccion.transacciones (estado);

CREATE INDEX IF NOT EXISTS idx_tx_tipo
    ON produccion.transacciones (tipo_transaccion);

CREATE INDEX IF NOT EXISTS idx_tx_riesgo_alto
    ON produccion.transacciones (riesgo_score DESC)
    WHERE riesgo_score > 0.5;

CREATE INDEX IF NOT EXISTS idx_tx_monto
    ON produccion.transacciones (monto);

-- fraude
CREATE INDEX IF NOT EXISTS idx_fraude_tx
    ON produccion.fraude (transaccion_id);

CREATE INDEX IF NOT EXISTS idx_fraude_flag
    ON produccion.fraude (flag_fraude)
    WHERE flag_fraude = TRUE;

CREATE INDEX IF NOT EXISTS idx_fraude_estado
    ON produccion.fraude (estado_revision)
    WHERE estado_revision IN ('pendiente','en_revision');

-- segmentacion
CREATE INDEX IF NOT EXISTS idx_segmentacion_usuario
    ON produccion.segmentacion (usuario_id);

CREATE INDEX IF NOT EXISTS idx_segmentacion_cluster
    ON produccion.segmentacion (cluster_ml);

-- campañas / braze
CREATE INDEX IF NOT EXISTS idx_campanas_estado
    ON produccion.campanas (estado);

CREATE INDEX IF NOT EXISTS idx_braze_email_env_usr
    ON produccion.braze_email_envios (usuario_id);

CREATE INDEX IF NOT EXISTS idx_braze_wa_env_usr
    ON produccion.braze_whatsapp_envios (usuario_id);

-- ============================================================
-- ██████████  TRIGGERS updated_at  ██████████
-- ============================================================

CREATE TRIGGER trg_usuarios_upd
    BEFORE UPDATE ON produccion.usuarios
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_merchants_upd
    BEFORE UPDATE ON produccion.merchants
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_tarjetas_upd
    BEFORE UPDATE ON produccion.tarjetas
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_aplicacion_upd
    BEFORE UPDATE ON produccion.aplicacion
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_campanas_upd
    BEFORE UPDATE ON produccion.campanas
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_pagos_upd
    BEFORE UPDATE ON produccion.pagos
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_fraude_upd
    BEFORE UPDATE ON produccion.fraude
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_demographics_upd
    BEFORE UPDATE ON produccion.usuarios_demographics
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

CREATE TRIGGER trg_etl_control_upd
    BEFORE UPDATE ON produccion.etl_control
    FOR EACH ROW EXECUTE FUNCTION produccion.fn_set_updated_at();

-- ============================================================
-- ██████████  VISTAS ANALÍTICAS  ██████████
-- ============================================================

-- Vista: transacciones enriquecidas
CREATE OR REPLACE VIEW produccion.vw_transacciones_completas AS
SELECT
    t.transaccion_id,
    t.transaction_id_origen,
    t.fecha_transaccion,
    t.tipo_transaccion,
    t.subtipo_transaccion,
    t.monto,
    t.moneda,
    t.canal,
    t.estado,
    t.costo_operativo,
    t.ingreso_comision,
    t.margen,
    t.riesgo_score,
    u.customer_id_origen          AS cliente_id_origen,
    u.nivel_riesgo                AS cliente_nivel_riesgo,
    u.pais                        AS cliente_pais,
    u.ciudad                      AS cliente_ciudad,
    m.nombre_comercio,
    m.categoria                   AS merchant_categoria,
    m.segmento                    AS merchant_segmento,
    m.mcc_code,
    m.ciudad                      AS merchant_ciudad,
    m.estado_region               AS merchant_estado,
    ta.tipo_tarjeta,
    ta.marca                      AS tarjeta_marca,
    f.flag_fraude,
    f.score_fraude,
    f.tipo_alerta                 AS fraude_tipo_alerta,
    f.estado_revision             AS fraude_estado
FROM produccion.transacciones t
JOIN produccion.usuarios   u  ON t.usuario_origen_id = u.usuario_id
LEFT JOIN produccion.merchants  m  ON t.merchant_id      = m.merchant_id
LEFT JOIN produccion.tarjetas   ta ON t.tarjeta_id       = ta.tarjeta_id
LEFT JOIN produccion.fraude     f  ON t.transaccion_id   = f.transaccion_id
                                   AND t.fecha_transaccion = f.fecha_transaccion;

-- Vista: resumen de usuarios
CREATE OR REPLACE VIEW produccion.vw_usuarios_resumen AS
SELECT
    u.usuario_id,
    u.customer_id_origen,
    u.estado,
    u.nivel_riesgo,
    u.pais,
    u.ciudad,
    u.score_actividad,
    u.score_rentabilidad,
    u.fecha_registro,
    COUNT(t.transaccion_id)           AS total_transacciones,
    SUM(t.monto)                      AS volumen_total,
    AVG(t.monto)                      AS ticket_promedio,
    SUM(t.margen)                     AS margen_total,
    COUNT(f.fraude_id)                AS alertas_fraude,
    s.segmento_transaccional,
    s.segmento_rentabilidad,
    s.cluster_ml
FROM produccion.usuarios u
LEFT JOIN produccion.transacciones  t  ON u.usuario_id = t.usuario_origen_id
LEFT JOIN produccion.fraude         f  ON t.transaccion_id = f.transaccion_id
                                       AND t.fecha_transaccion = f.fecha_transaccion
                                       AND f.flag_fraude = TRUE
LEFT JOIN produccion.segmentacion   s  ON u.usuario_id = s.usuario_id
GROUP BY
    u.usuario_id, u.customer_id_origen, u.estado, u.nivel_riesgo,
    u.pais, u.ciudad, u.score_actividad, u.score_rentabilidad, u.fecha_registro,
    s.segmento_transaccional, s.segmento_rentabilidad, s.cluster_ml;

-- Vista: alertas de fraude activas
CREATE OR REPLACE VIEW produccion.vw_fraude_activo AS
SELECT
    f.fraude_id,
    f.transaccion_id,
    f.tipo_alerta,
    f.score_fraude,
    f.estado_revision,
    f.fecha_deteccion,
    t.monto,
    t.fecha_transaccion,
    t.canal,
    u.customer_id_origen,
    m.nombre_comercio,
    m.categoria AS merchant_categoria
FROM produccion.fraude f
JOIN produccion.transacciones t ON f.transaccion_id = t.transaccion_id
                                AND f.fecha_transaccion = t.fecha_transaccion
JOIN produccion.usuarios      u ON t.usuario_origen_id = u.usuario_id
LEFT JOIN produccion.merchants m ON t.merchant_id = m.merchant_id
WHERE f.flag_fraude = TRUE
  AND f.estado_revision IN ('pendiente','en_revision')
ORDER BY f.score_fraude DESC;

-- ============================================================
-- ██████████  DATOS INICIALES  ██████████
-- ============================================================

-- Control ETL inicial
INSERT INTO produccion.etl_control (nombre_proceso, registros_procesados, estado_ultimo_proceso)
VALUES
    ('carga_inicial_ibm',       0, 'pendiente'),
    ('actualizacion_incremental', 0, 'pendiente'),
    ('recalculo_scores',        0, 'pendiente'),
    ('segmentacion_usuarios',   0, 'pendiente')
ON CONFLICT (nombre_proceso) DO NOTHING;

-- Registro de migración inicial
INSERT INTO produccion.schema_migrations (version, nombre, checksum)
VALUES ('1.0.0', 'initial_schema_ibm_fintech', md5('initial_schema_ibm_fintech_v1_0_0'))
ON CONFLICT (version) DO NOTHING;
