# Documento 09 — Casos de Uso Analíticos
## PayNova S.A. — Escenarios de Negocio y Análisis Tipo

**Versión:** 1.0  
**Propósito:** Guía de referencia para analistas, agentes SQL y benchmarks de evaluación. Cada caso de uso incluye contexto de negocio, pregunta analítica, tablas requeridas y SQL de referencia.  
**Referencias cruzadas:** `06_metrics_catalog.md`, `07_business_rules.md`, `08_executive_kpis.md`, `10_agent_knowledge_base.md`

---

## CASO DE USO 01 — Análisis de Rentabilidad por Período

**Área:** CFO / Finanzas  
**Frecuencia:** Mensual  
**Descripción del escenario:** El CFO necesita ver el waterfall de rentabilidad del último mes: cuánto se generó en GMV, cuánto en MDR, cuáles fueron los costos de procesamiento, qué quedó como margen bruto, cuánto se gastó en notificaciones, y cuál fue el margen neto final.

**Tablas requeridas:** `transacciones.transacciones`, `produccion.notificaciones`

**Pregunta tipo:** "¿Cuál fue el margen neto ajustado del mes pasado y cómo se compara con el mismo mes del año anterior?"

```sql
WITH mes_actual AS (
    SELECT
        'mes_actual' AS periodo,
        SUM(monto) AS gmv,
        SUM(ingreso_comision) AS mdr,
        SUM(costo_operativo) AS costo_procesamiento,
        SUM(margen) AS margen_bruto
    FROM transacciones.transacciones
    WHERE estado = 'completada'
      AND year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')
),
mes_anterior_anio AS (
    SELECT
        'mismo_mes_anio_anterior' AS periodo,
        SUM(monto) AS gmv,
        SUM(ingreso_comision) AS mdr,
        SUM(costo_operativo) AS costo_procesamiento,
        SUM(margen) AS margen_bruto
    FROM transacciones.transacciones
    WHERE estado = 'completada'
      AND year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '13 months', 'YYYY-MM')
),
notif_mes AS (
    SELECT SUM(costo_total) AS costo_notif
    FROM produccion.notificaciones
    WHERE TO_CHAR(DATE_TRUNC('month', fecha_envio), 'YYYY-MM') =
          TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')
)
SELECT
    b.periodo,
    ROUND(b.gmv, 2) AS gmv,
    ROUND(b.mdr, 2) AS ingresos_mdr,
    ROUND(b.mdr / NULLIF(b.gmv, 0) * 100, 4) AS mdr_rate_pct,
    ROUND(b.costo_procesamiento, 2) AS costo_procesamiento,
    ROUND(b.margen_bruto, 2) AS margen_bruto,
    ROUND(COALESCE(n.costo_notif, 0), 2) AS costo_notificaciones,
    ROUND(b.margen_bruto - COALESCE(n.costo_notif, 0), 2) AS margen_neto_ajustado,
    ROUND((b.margen_bruto - COALESCE(n.costo_notif, 0)) / NULLIF(b.gmv, 0) * 100, 4) AS pct_margen_neto
FROM (SELECT * FROM mes_actual UNION ALL SELECT * FROM mes_anterior_anio) b
LEFT JOIN notif_mes n ON b.periodo = 'mes_actual';
```

---

## CASO DE USO 02 — Análisis de Churn de Comercios

**Área:** Dirección Comercial  
**Frecuencia:** Mensual  
**Descripción del escenario:** El equipo comercial necesita identificar qué comercios estuvieron activos el mes pasado pero no han procesado transacciones en el mes actual. Estos son candidatos a campañas de reactivación o llamadas de seguimiento por Account Manager.

**Tablas requeridas:** `transacciones.transacciones`, `produccion.merchants`, `produccion.account_managers`

**Pregunta tipo:** "¿Qué comercios dejaron de transaccionar este mes? ¿A quién están asignados?"

```sql
WITH mes_pasado AS (
    SELECT DISTINCT merchant_id
    FROM transacciones.transacciones
    WHERE estado = 'completada'
      AND year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')
),
mes_actual AS (
    SELECT DISTINCT merchant_id
    FROM transacciones.transacciones
    WHERE estado = 'completada'
      AND year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE), 'YYYY-MM')
),
churned AS (
    SELECT merchant_id FROM mes_pasado
    EXCEPT
    SELECT merchant_id FROM mes_actual
)
SELECT
    m.merchant_id,
    m.merchant_name,
    m.mcc_categoria,
    m.status_operacional,
    sm.segmento_volumen,
    sm.segmento_rentabilidad,
    am.nombre AS account_manager,
    am.email AS email_manager,
    m.ultima_actividad
FROM churned c
JOIN produccion.merchants m ON c.merchant_id = m.merchant_id
LEFT JOIN produccion.segmentacion_merchants sm ON m.merchant_id = sm.merchant_id
LEFT JOIN produccion.account_managers am ON m.coordinador_id = am.manager_id
WHERE m.status_operacional = 'activo'
ORDER BY sm.segmento_volumen DESC, m.ultima_actividad ASC;
```

---

## CASO DE USO 03 — Activación de Usuarios Nuevos

**Área:** Marketing  
**Frecuencia:** Semanal  
**Descripción del escenario:** El equipo de marketing quiere saber qué cohorte de usuarios registrados en los últimos 3 meses tiene la menor tasa de activación (no han realizado su primera transacción). Estos usuarios deben recibir una campaña de onboarding con incentivo de primera transacción.

**Tablas requeridas:** `produccion.usuarios`, `transacciones.transacciones`

**Pregunta tipo:** "¿Qué porcentaje de usuarios registrados en los últimos 90 días no ha transaccionado aún?"

```sql
WITH registros AS (
    SELECT
        usuario_id,
        fecha_registro,
        DATE_TRUNC('week', fecha_registro) AS cohorte_semana
    FROM produccion.usuarios
    WHERE fecha_registro >= CURRENT_DATE - 90
      AND estado NOT IN ('suspendido', 'bloqueado')
),
primera_tx AS (
    SELECT
        usuario_origen_id,
        MIN(fecha_transaccion) AS primera_transaccion
    FROM transacciones.transacciones
    WHERE estado = 'completada'
    GROUP BY usuario_origen_id
)
SELECT
    TO_CHAR(r.cohorte_semana, 'IYYY-IW') AS semana_cohorte,
    COUNT(r.usuario_id) AS usuarios_registrados,
    COUNT(p.usuario_origen_id) AS usuarios_activados,
    COUNT(r.usuario_id) - COUNT(p.usuario_origen_id) AS usuarios_no_activados,
    ROUND(COUNT(p.usuario_origen_id)::NUMERIC / COUNT(r.usuario_id) * 100, 2) AS tasa_activacion_pct,
    ROUND(AVG(p.primera_transaccion - r.fecha_registro), 1) AS dias_promedio_primera_tx
FROM registros r
LEFT JOIN primera_tx p ON r.usuario_id = p.usuario_origen_id
GROUP BY r.cohorte_semana
ORDER BY r.cohorte_semana;
```

---

## CASO DE USO 04 — Reactivación de Usuarios Inactivos

**Área:** Marketing / CRM  
**Frecuencia:** Mensual  
**Descripción del escenario:** Identificar usuarios que llevan entre 90 y 180 días sin transaccionar (candidatos óptimos para win-back) y calcular su valor histórico para priorizar la campaña.

**Tablas requeridas:** `produccion.usuarios`, `transacciones.transacciones`, `produccion.segmentacion`

**Pregunta tipo:** "¿Cuáles son mis 500 mejores usuarios inactivos para una campaña de reactivación?"

```sql
WITH ultima_tx AS (
    SELECT
        usuario_origen_id,
        MAX(fecha_transaccion) AS ultima_transaccion,
        COUNT(*) AS total_transacciones_historicas,
        SUM(monto) AS gmv_historico
    FROM transacciones.transacciones
    WHERE estado = 'completada'
    GROUP BY usuario_origen_id
),
candidatos AS (
    SELECT
        u.usuario_id,
        u.estado,
        u.nivel_riesgo,
        ut.ultima_transaccion,
        ut.total_transacciones_historicas,
        ut.gmv_historico,
        CURRENT_DATE - ut.ultima_transaccion::DATE AS dias_inactivo
    FROM produccion.usuarios u
    JOIN ultima_tx ut ON u.usuario_id = ut.usuario_origen_id
    WHERE u.estado NOT IN ('suspendido', 'bloqueado')
      AND u.nivel_riesgo != 'critico'
      AND (CURRENT_DATE - ut.ultima_transaccion::DATE) BETWEEN 90 AND 180
)
SELECT
    c.usuario_id,
    c.dias_inactivo,
    c.total_transacciones_historicas,
    ROUND(c.gmv_historico, 2) AS gmv_historico,
    ROUND(c.gmv_historico / c.total_transacciones_historicas, 2) AS ticket_promedio_historico,
    s.segmento_transaccional,
    s.segmento_rentabilidad
FROM candidatos c
LEFT JOIN produccion.segmentacion s ON c.usuario_id = s.usuario_id
ORDER BY c.gmv_historico DESC
LIMIT 500;
```

---

## CASO DE USO 05 — Análisis de Fraude por Segmento y Canal

**Área:** Riesgo  
**Frecuencia:** Semanal  
**Descripción del escenario:** El equipo de riesgo quiere entender en qué canal (`canal_pago`) y en qué rango horario ocurren más eventos de fraude, para ajustar las reglas del modelo de detección.

**Tablas requeridas:** `transacciones.transacciones`, `produccion.fraude`

**Pregunta tipo:** "¿En qué canal y hora del día se concentra el fraude? ¿Cuál es la tasa por combinación?"

```sql
SELECT
    t.canal_pago,
    t.hora_transaccion,
    COUNT(*) AS total_transacciones,
    COUNT(CASE WHEN f.flag_fraude = TRUE THEN 1 END) AS fraudes,
    ROUND(COUNT(CASE WHEN f.flag_fraude = TRUE THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 4) AS tasa_fraude_pct,
    ROUND(SUM(CASE WHEN f.flag_fraude = TRUE THEN t.monto ELSE 0 END), 2) AS monto_fraudulento,
    ROUND(AVG(CASE WHEN f.flag_fraude = TRUE THEN t.riesgo_score END), 4) AS score_promedio_fraude
FROM transacciones.transacciones t
LEFT JOIN produccion.fraude f ON t.transaccion_id = f.transaccion_id
WHERE t.fecha_transaccion >= CURRENT_DATE - 90
GROUP BY t.canal_pago, t.hora_transaccion
ORDER BY tasa_fraude_pct DESC, total_transacciones DESC;
```

---

## CASO DE USO 06 — Optimización de Canales de Comunicación (Análisis Pareto)

**Área:** Marketing / Finanzas  
**Frecuencia:** Mensual  
**Descripción del escenario:** El equipo quiere entender qué comercios están generando el mayor costo en notificaciones, para identificar si el gasto es proporcional al ingreso que generan o si hay comercios que reciben muchas notificaciones con bajo retorno.

**Tablas requeridas:** `produccion.notificaciones`, `produccion.merchants`, `transacciones.transacciones`

**Pregunta tipo:** "¿Cuáles son los 20 comercios con mayor costo de notificaciones? ¿Es proporcional a su MDR?"

```sql
WITH costo_notif AS (
    SELECT
        merchant_id,
        SUM(costo_total) AS costo_notificaciones,
        COUNT(*) AS envios,
        SUM(cantidad_enviada) AS mensajes_enviados
    FROM produccion.notificaciones
    WHERE fecha_envio >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
      AND fecha_envio < DATE_TRUNC('month', CURRENT_DATE)
    GROUP BY merchant_id
),
mdr_por_comercio AS (
    SELECT
        merchant_id,
        SUM(ingreso_comision) AS mdr_generado,
        SUM(monto) AS gmv
    FROM transacciones.transacciones
    WHERE estado = 'completada'
      AND year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')
    GROUP BY merchant_id
)
SELECT
    m.merchant_id,
    m.merchant_name,
    sm.segmento_volumen,
    ROUND(COALESCE(r.mdr_generado, 0), 2) AS mdr_generado,
    ROUND(COALESCE(n.costo_notificaciones, 0), 2) AS costo_notificaciones,
    ROUND(COALESCE(n.costo_notificaciones, 0) / NULLIF(r.mdr_generado, 0) * 100, 2) AS ratio_costo_mdr_pct,
    n.envios,
    n.mensajes_enviados
FROM costo_notif n
JOIN produccion.merchants m ON n.merchant_id = m.merchant_id
LEFT JOIN produccion.segmentacion_merchants sm ON m.merchant_id = sm.merchant_id
LEFT JOIN mdr_por_comercio r ON n.merchant_id = r.merchant_id
ORDER BY n.costo_notificaciones DESC
LIMIT 20;
```

---

## CASO DE USO 07 — Análisis de Efectividad del Funnel de Onboarding

**Área:** Operaciones / Comercial  
**Frecuencia:** Mensual  
**Descripción del escenario:** El equipo operativo quiere saber cuántos comercios abandonan el proceso de onboarding en cada etapa y cuánto tiempo demoran en avanzar, para identificar dónde intervenir.

**Tablas requeridas:** `produccion.vw_funnel_comercios` (vista) o tablas base

**Pregunta tipo:** "¿Cuál es la tasa de conversión en cada etapa del funnel de comercios?"

```sql
-- Usando la vista materializada del funnel
SELECT * FROM produccion.vw_funnel_comercios;

-- Si se necesita el detalle por etapa con cálculo manual:
WITH base AS (
    SELECT COUNT(*) AS total_registrados FROM produccion.merchants WHERE status_operacional != 'eliminado'
),
integrados AS (
    SELECT COUNT(DISTINCT merchant_id) AS total
    FROM produccion.integraciones_merchant
    WHERE estado_integracion = 'activa' AND api_key_validado = TRUE
),
activos AS (
    SELECT COUNT(DISTINCT merchant_id) AS total
    FROM produccion.merchants
    WHERE status_operacional = 'activo'
      AND ultima_actividad >= CURRENT_DATE - 30
),
con_notificaciones AS (
    SELECT COUNT(DISTINCT merchant_id) AS total
    FROM produccion.integraciones_merchant
    WHERE (email_integrado = TRUE OR sms_integrado = TRUE)
      AND estado_integracion = 'activa'
),
con_transacciones AS (
    SELECT COUNT(DISTINCT merchant_id) AS total
    FROM transacciones.transacciones
    WHERE estado = 'completada'
),
con_payouts AS (
    SELECT COUNT(DISTINCT merchant_id) AS total
    FROM produccion.payouts
    WHERE estado = 'procesado'
)
SELECT
    b.total_registrados,
    i.total AS integrados,
    a.total AS activos,
    cn.total AS con_notificaciones,
    ct.total AS con_transacciones,
    cp.total AS con_payouts,
    ROUND(i.total::NUMERIC / NULLIF(b.total_registrados, 0) * 100, 1) AS conv_reg_a_integ_pct,
    ROUND(a.total::NUMERIC / NULLIF(i.total, 0) * 100, 1) AS conv_integ_a_activo_pct,
    ROUND(ct.total::NUMERIC / NULLIF(a.total, 0) * 100, 1) AS conv_activo_a_tx_pct,
    ROUND(cp.total::NUMERIC / NULLIF(ct.total, 0) * 100, 1) AS conv_tx_a_payout_pct
FROM base b, integrados i, activos a, con_notificaciones cn, con_transacciones ct, con_payouts cp;
```

---

## CASO DE USO 08 — Análisis de Canibalización de Campañas

**Área:** Marketing  
**Frecuencia:** Post-campaña  
**Descripción del escenario:** El equipo de marketing lanzó una campaña de cashback para incentivar transacciones en supermercados (MCC 5411) en enero 2019. Se quiere saber si la campaña generó volumen incremental o si canibalizó transacciones que de todas formas habrían ocurrido.

**Tablas requeridas:** `transacciones.transacciones`  
**Metodología:** Comparar el comportamiento de los usuarios antes y durante la campaña.

**Pregunta tipo:** "¿La campaña de cashback en supermercados generó más transacciones o solo cambió cuándo ocurrieron?"

```sql
-- Transacciones en supermercados (MCC 5411): período pre-campaña vs. durante campaña
WITH pre_campana AS (
    SELECT
        'pre_campana_nov_dic_2018' AS periodo,
        COUNT(*) AS total_tx,
        COUNT(DISTINCT usuario_origen_id) AS usuarios_unicos,
        SUM(monto) AS gmv,
        ROUND(AVG(monto), 2) AS ticket_promedio
    FROM transacciones.transacciones t
    JOIN produccion.merchants m ON t.merchant_id = m.merchant_id
    WHERE m.mcc = '5411'
      AND t.estado = 'completada'
      AND t.year_month IN ('2018-11', '2018-12')
),
durante_campana AS (
    SELECT
        'durante_campana_ene_feb_2019' AS periodo,
        COUNT(*) AS total_tx,
        COUNT(DISTINCT usuario_origen_id) AS usuarios_unicos,
        SUM(monto) AS gmv,
        ROUND(AVG(monto), 2) AS ticket_promedio
    FROM transacciones.transacciones t
    JOIN produccion.merchants m ON t.merchant_id = m.merchant_id
    WHERE m.mcc = '5411'
      AND t.estado = 'completada'
      AND t.year_month IN ('2019-01', '2019-02')
)
SELECT * FROM pre_campana
UNION ALL
SELECT * FROM durante_campana;
```

---

## CASO DE USO 09 — Análisis de Segmentación por RFM (Comercios)

**Área:** Estrategia Comercial / Account Management  
**Frecuencia:** Mensual  
**Descripción del escenario:** El equipo comercial quiere construir la matriz estratégica de comercios: GMV (eje X) vs. MDR rentabilidad (eje Y), para identificar cuáles son los comercios que más contribuyen al negocio y cuáles requieren intervención.

**Tablas requeridas:** `transacciones.transacciones`, `produccion.merchants`, `produccion.segmentacion_merchants`, `produccion.account_managers`

**Pregunta tipo:** "¿Cuáles son nuestros comercios estrella por GMV y rentabilidad? ¿Quién los gestiona?"

```sql
SELECT
    m.merchant_id,
    m.merchant_name,
    m.mcc_categoria,
    sm.segmento_volumen,
    sm.segmento_rentabilidad,
    am.nombre AS account_manager,
    COUNT(t.transaccion_id) AS total_transacciones,
    ROUND(SUM(t.monto), 2) AS gmv_mensual,
    ROUND(SUM(t.ingreso_comision), 2) AS mdr_mensual,
    ROUND(SUM(t.margen), 2) AS margen_mensual,
    ROUND(SUM(t.ingreso_comision) / NULLIF(SUM(t.monto), 0) * 100, 4) AS mdr_rate_efectivo_pct,
    ROUND(AVG(t.monto), 2) AS ticket_promedio,
    CASE
        WHEN sm.segmento_volumen IN ('grande', 'mega') AND sm.segmento_rentabilidad IN ('gold', 'platinum', 'diamond') THEN 'Estrella'
        WHEN sm.segmento_volumen IN ('grande', 'mega') AND sm.segmento_rentabilidad IN ('silver', 'bronze') THEN 'Alto Volumen Bajo Margen'
        WHEN sm.segmento_volumen IN ('micro', 'pequeno') AND sm.segmento_rentabilidad IN ('gold', 'platinum', 'diamond') THEN 'Nicho Rentable'
        ELSE 'Estándar'
    END AS cuadrante_estrategico
FROM produccion.merchants m
JOIN transacciones.transacciones t ON m.merchant_id = t.merchant_id
LEFT JOIN produccion.segmentacion_merchants sm ON m.merchant_id = sm.merchant_id
LEFT JOIN produccion.account_managers am ON m.coordinador_id = am.manager_id
WHERE t.estado = 'completada'
  AND t.year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')
GROUP BY m.merchant_id, m.merchant_name, m.mcc_categoria, sm.segmento_volumen, sm.segmento_rentabilidad, am.nombre
ORDER BY gmv_mensual DESC;
```

---

## CASO DE USO 10 — Análisis de Efectividad por Account Manager

**Área:** Dirección Comercial  
**Frecuencia:** Mensual  
**Descripción del escenario:** La Dirección Comercial quiere evaluar el rendimiento de cada Account Manager basado en el GMV y MDR generado por el portafolio de comercios que gestiona, para identificar managers de alto y bajo rendimiento.

**Tablas requeridas:** `produccion.account_managers`, `produccion.merchants`, `transacciones.transacciones`

**Pregunta tipo:** "¿Cuál es el rendimiento de cada Account Manager? ¿Cuánto GMV gestiona su portafolio?"

```sql
SELECT
    am.manager_id,
    am.nombre AS account_manager,
    am.region,
    COUNT(DISTINCT m.merchant_id) AS total_comercios_asignados,
    COUNT(DISTINCT CASE WHEN m.ultima_actividad >= CURRENT_DATE - 30 THEN m.merchant_id END) AS comercios_activos,
    ROUND(COUNT(DISTINCT CASE WHEN m.ultima_actividad >= CURRENT_DATE - 30 THEN m.merchant_id END)::NUMERIC /
          NULLIF(COUNT(DISTINCT m.merchant_id), 0) * 100, 2) AS pct_portafolio_activo,
    ROUND(SUM(t.monto), 2) AS gmv_portafolio,
    ROUND(SUM(t.ingreso_comision), 2) AS mdr_portafolio,
    ROUND(SUM(t.margen), 2) AS margen_portafolio,
    ROUND(AVG(t.monto), 2) AS ticket_promedio_portafolio,
    ROUND(SUM(t.monto) / NULLIF(COUNT(DISTINCT m.merchant_id), 0), 2) AS gmv_por_comercio_asignado
FROM produccion.account_managers am
LEFT JOIN produccion.merchants m ON am.manager_id = m.coordinador_id
LEFT JOIN transacciones.transacciones t ON m.merchant_id = t.merchant_id
    AND t.estado = 'completada'
    AND t.year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')
WHERE am.estado = 'activo'
GROUP BY am.manager_id, am.nombre, am.region
ORDER BY gmv_portafolio DESC;
```

---

## CASO DE USO 11 — Serie Temporal de Transacciones con Media Móvil

**Área:** CEO / Analytics  
**Frecuencia:** Semanal  
**Descripción del escenario:** El CEO quiere ver la tendencia del GMV mensual de los últimos 24 meses con una media móvil de 3 meses para suavizar la estacionalidad y ver la tendencia real.

**Tablas requeridas:** `transacciones.transacciones`

**Pregunta tipo:** "¿Cuál es la tendencia del GMV en los últimos 2 años con suavizado?"

```sql
WITH gmv_mensual AS (
    SELECT
        year_month,
        SUM(monto) AS gmv,
        SUM(ingreso_comision) AS mdr,
        COUNT(*) AS transacciones,
        COUNT(DISTINCT merchant_id) AS comercios_activos
    FROM transacciones.transacciones
    WHERE estado = 'completada'
      AND year_month >= TO_CHAR(CURRENT_DATE - INTERVAL '24 months', 'YYYY-MM')
    GROUP BY year_month
)
SELECT
    year_month,
    ROUND(gmv, 2) AS gmv_mensual,
    ROUND(mdr, 2) AS mdr_mensual,
    transacciones,
    comercios_activos,
    ROUND(AVG(gmv) OVER (ORDER BY year_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS gmv_media_movil_3m,
    ROUND(gmv / LAG(gmv, 12) OVER (ORDER BY year_month) * 100 - 100, 2) AS crecimiento_yoy_pct,
    ROUND(gmv / LAG(gmv, 1) OVER (ORDER BY year_month) * 100 - 100, 2) AS crecimiento_mom_pct
FROM gmv_mensual
ORDER BY year_month;
```

---

## CASO DE USO 12 — Análisis de Heatmap de Rechazos por Hora y Día

**Área:** COO / Operaciones  
**Frecuencia:** Semanal  
**Descripción del escenario:** El equipo de operaciones necesita identificar patrones en los rechazos transaccionales por hora del día y día de la semana para detectar ventanas de alto riesgo operativo o técnico.

**Tablas requeridas:** `transacciones.transacciones`

**Pregunta tipo:** "¿En qué horas y días hay más rechazos? ¿Hay algún patrón recurrente?"

```sql
SELECT
    dia_semana,
    hora_transaccion,
    COUNT(*) AS total_intentos,
    COUNT(CASE WHEN estado = 'completada' THEN 1 END) AS completadas,
    COUNT(CASE WHEN estado = 'rechazada' THEN 1 END) AS rechazadas,
    COUNT(CASE WHEN estado = 'error' THEN 1 END) AS errores,
    ROUND(COUNT(CASE WHEN estado = 'rechazada' THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) AS tasa_rechazo_pct,
    ROUND(AVG(monto), 2) AS monto_promedio
FROM transacciones.transacciones
WHERE fecha_transaccion >= CURRENT_DATE - 90
GROUP BY dia_semana, hora_transaccion
ORDER BY tasa_rechazo_pct DESC;
```
