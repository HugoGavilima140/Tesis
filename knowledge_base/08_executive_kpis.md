# Documento 08 — KPIs Ejecutivos por Rol
## PayNova S.A. — Panel de Control para Dirección

**Versión:** 1.0  
**Propósito:** Definición de los KPIs que cada C-level monitorea, con umbrales de acción y queries de referencia.  
**Referencias cruzadas:** `06_metrics_catalog.md`, `07_business_rules.md`, `09_analytics_use_cases.md`

---

## ROL: CEO — Director General

**Enfoque:** Crecimiento, rentabilidad total, posición competitiva y salud general del negocio.  
**Frecuencia de revisión:** Semanal / Mensual

| KPI | Descripción | Fórmula | Meta | Alerta Roja | Acción sugerida |
|-----|-------------|---------|------|-------------|-----------------|
| GMV Total | Volumen bruto mensual de transacciones completadas | `SUM(monto) WHERE estado='completada'` | Crecimiento ≥ 15% YoY | Caída > 5% vs mes anterior | Revisar canales y comercios de mayor volumen |
| Comercios Activos | Comercios con actividad en los últimos 30 días | `COUNT(DISTINCT merchant_id) con tx en 30d` | > 2,500 | < 2,000 | Revisar tasa de churn de comercios y efectividad del onboarding |
| Ingresos por MDR | MDR total generado en el período | `SUM(ingreso_comision) WHERE estado='completada'` | 1.8% del GMV | < 1.6% del GMV (posible acuerdo de MDR sub-estándar sin aprobación) | Auditar comercios con MDR efectivo < 1.8% |
| Margen Bruto Transaccional | Rentabilidad directa del negocio antes de costos fijos | `SUM(margen) WHERE estado='completada'` | ≥ 1.0% del GMV | < 0.8% | Revisar estructura de costos operativos |
| Tasa de Aprobación | % de transacciones exitosas sobre intentadas | `COUNT(completadas)/COUNT(total)` | ≥ 97% | < 94% | Alerta de crisis operativa — activar protocolo de contingencia |
| Tasa de Fraude | % de transacciones fraudulentas sobre total | `COUNT(fraude)/COUNT(total)` | < 0.5% | > 2% | Revisión urgente con equipo de riesgo |
| NPS implícito (Reactivación) | Tasa de usuarios inactivos que regresan | `COUNT(reactivados)/COUNT(inactivos_90d)` | > 15% | < 5% | Revisar estrategia de retención y propuesta de valor |

**Query de resumen ejecutivo mensual:**
```sql
SELECT
    year_month,
    COUNT(*) AS total_transacciones,
    COUNT(CASE WHEN estado = 'completada' THEN 1 END) AS completadas,
    ROUND(SUM(CASE WHEN estado = 'completada' THEN monto ELSE 0 END)::NUMERIC, 2) AS gmv,
    ROUND(SUM(CASE WHEN estado = 'completada' THEN ingreso_comision ELSE 0 END)::NUMERIC, 2) AS ingresos_mdr,
    ROUND(SUM(CASE WHEN estado = 'completada' THEN margen ELSE 0 END)::NUMERIC, 2) AS margen_bruto,
    ROUND(COUNT(CASE WHEN estado = 'completada' THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) AS tasa_aprobacion_pct
FROM transacciones.transacciones
WHERE year_month >= TO_CHAR(CURRENT_DATE - INTERVAL '12 months', 'YYYY-MM')
GROUP BY year_month
ORDER BY year_month;
```

---

## ROL: CFO — Director Financiero

**Enfoque:** Rentabilidad, estructura de costos, eficiencia del capital, gestión de payouts y exposición financiera.  
**Frecuencia de revisión:** Diaria (alertas) / Semanal (revisión completa)

| KPI | Descripción | Fórmula | Meta | Alerta Roja | Acción sugerida |
|-----|-------------|---------|------|-------------|-----------------|
| MDR Rate Efectivo | Tasa real de MDR cobrada al portafolio | `SUM(ingreso_comision)/SUM(monto)*100 WHERE completada` | 1.80% | < 1.70% | Auditar comercios con descuentos no autorizados |
| Costo Operativo por Transacción | Costo promedio unitario de procesamiento | `SUM(costo_operativo)/COUNT(completadas)` | < $0.12 | > $0.18 | Revisar estructura de costos con proveedor de red |
| Monto Total Desembolsado (Payouts) | Total liquidado a comercios en el período | `SUM(monto_neto) WHERE estado='procesado'` | Controlado por GMV | Discrepancia > 5% con GMV esperado | Auditoría de reconciliación |
| Tasa de Éxito de Payouts | % de payouts procesados exitosamente | `COUNT(procesado)/COUNT(total) FROM payouts` | ≥ 99% | < 97% | Investigar razones de rechazo; revisar datos bancarios |
| Costo de Notificaciones / MDR | Proporción del MDR consumida en comunicaciones | `SUM(n.costo_total)/SUM(t.ingreso_comision)*100` | < 5% | > 10% | Optimizar mezcla de canales hacia canales de menor costo |
| Margen Neto Ajustado | GMV − MDR retenido − costos de notificación | Waterfall completo | ≥ 0.8% del GMV | < 0.5% | Revisión urgente de estructura de costos |
| Monto en Riesgo (Fraude) | Exposición financiera por fraude no resuelto | `SUM(monto) FROM transacciones JOIN fraude WHERE estado_revision='pendiente'` | < $50,000 | > $200,000 | Acelerar proceso de revisión; aumentar recursos de análisis |

**Query de waterfall financiero mensual:**
```sql
WITH base AS (
    SELECT
        year_month,
        SUM(monto) AS gmv,
        SUM(ingreso_comision) AS mdr_total,
        SUM(costo_operativo) AS costo_procesamiento,
        SUM(margen) AS margen_bruto
    FROM transacciones.transacciones
    WHERE estado = 'completada'
    GROUP BY year_month
),
notif AS (
    SELECT
        TO_CHAR(DATE_TRUNC('month', fecha_envio), 'YYYY-MM') AS year_month,
        SUM(costo_total) AS costo_notif
    FROM produccion.notificaciones
    GROUP BY 1
)
SELECT
    b.year_month,
    ROUND(b.gmv, 2) AS gmv,
    ROUND(b.mdr_total, 2) AS ingresos_mdr,
    ROUND(b.costo_procesamiento, 2) AS costo_procesamiento,
    ROUND(b.margen_bruto, 2) AS margen_bruto,
    ROUND(COALESCE(n.costo_notif, 0), 2) AS costo_notificaciones,
    ROUND(b.margen_bruto - COALESCE(n.costo_notif, 0), 2) AS margen_neto_ajustado,
    ROUND((b.margen_bruto - COALESCE(n.costo_notif, 0)) / NULLIF(b.gmv, 0) * 100, 4) AS pct_margen_neto
FROM base b
LEFT JOIN notif n ON b.year_month = n.year_month
ORDER BY b.year_month;
```

---

## ROL: COO — Director de Operaciones

**Enfoque:** Eficiencia operativa, SLAs, uptime del sistema, calidad del servicio y gestión de incidentes.  
**Frecuencia de revisión:** Tiempo real (alertas) / Diaria

| KPI | Descripción | Fórmula | Meta | Alerta Roja | Acción sugerida |
|-----|-------------|---------|------|-------------|-----------------|
| Tasa de Aprobación | % de transacciones aprobadas | `completadas/total*100` | ≥ 97% | < 95% | Activar protocolo de incidente — verificar estado de red |
| Tiempo de Activación de Comercio | Días desde onboarding hasta primera tx | `AVG(primera_tx - inicio_integracion)` | ≤ 5 días hábiles | > 10 días | Revisar etapas del proceso; identificar cuello de botella |
| Eficiencia del Funnel de Comercios | Conversión total: Registrados → Con Payouts | `comercios_con_payouts/comercios_registrados` | > 70% | < 50% | Analizar pérdidas por etapa del funnel |
| Tasa de Rechazo por Canal | % de rechazos por canal específico | `COUNT(rechazadas)/COUNT(total) GROUP BY canal` | < 3% por canal | > 8% en algún canal | Investigar problema específico del canal afectado |
| Tasa de Éxito de Payouts | Payouts procesados exitosamente | `procesados/total FROM payouts` | ≥ 99% | < 97% | Investigar payouts fallidos — validar datos bancarios |
| Tasa de Rechazo de Notificaciones | % de mensajes no entregados | `rechazadas/total FROM notificaciones` | < 2% | > 5% | Limpiar listas de contacto; verificar proveedor de SMS/email |
| Alertas de Fraude Pendientes | Alertas sin resolver más allá del SLA | `COUNT(fraude) WHERE estado='pendiente' AND CURRENT_TS - fecha_deteccion > SLA` | 0 (dentro del SLA) | > 10 alertas críticas vencidas | Escalar a gerencia; asignar recursos adicionales |

**Query de salud operativa diaria:**
```sql
SELECT
    DATE(fecha_transaccion) AS fecha,
    COUNT(*) AS total_intentos,
    COUNT(CASE WHEN estado = 'completada' THEN 1 END) AS aprobadas,
    COUNT(CASE WHEN estado = 'rechazada' THEN 1 END) AS rechazadas,
    COUNT(CASE WHEN estado = 'error' THEN 1 END) AS errores,
    ROUND(COUNT(CASE WHEN estado = 'completada' THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) AS tasa_aprobacion,
    ROUND(AVG(CASE WHEN estado = 'rechazada' THEN 1.0 ELSE 0 END) * 100, 2) AS tasa_rechazo,
    COUNT(DISTINCT merchant_id) AS comercios_activos_del_dia
FROM transacciones.transacciones
WHERE fecha_transaccion >= CURRENT_DATE - 7
GROUP BY DATE(fecha_transaccion)
ORDER BY fecha DESC;
```

---

## ROL: DIRECTOR COMERCIAL

**Enfoque:** Crecimiento de la red de comercios, onboarding, retención y rentabilidad por comercio.  
**Frecuencia de revisión:** Semanal

| KPI | Descripción | Fórmula | Meta | Alerta Roja | Acción sugerida |
|-----|-------------|---------|------|-------------|-----------------|
| Nuevos Comercios Activos | Comercios que procesaron su primera tx en el mes | Ver RN-ACT-003 | ≥ 42 por mes | < 20 por mes | Revisar pipeline de ventas; aumentar prospección |
| GMV por Segmento de Comercio | Distribución del GMV entre segmentos de volumen | `SUM(monto) GROUP BY segmento_volumen` | Mega+Grande ≥ 60% del GMV | Mega+Grande < 40% | Priorizar retención de cuentas grandes |
| Tasa de Churn de Comercios | Comercios que dejaron de transaccionar | `Comercios activos mes anterior - activos este mes` | < 2% mensual | > 5% mensual | Activar campaña de recuperación; revisar satisfacción |
| MDR por Comercio Activo | Ingreso promedio por comercio activo | `SUM(ingreso_comision)/COUNT(DISTINCT merchant_id)` | > $1,500/mes | < $800/mes | Revisar composición de la cartera; identificar comercios de bajo rendimiento |
| Comercios en Funnel de Activación | Comercios en proceso de onboarding | `COUNT(integraciones WHERE estado_integracion='en_curso')` | Saludable según capacidad del equipo | > 200 comercios estancados > 15 días | Revisar cuellos de botella en el proceso de onboarding |
| NPS de Comercios (proxy) | Tasa de comercios que recomiendan el servicio | Encuesta externa (no en BD) | > 40 | < 20 | Revisar satisfacción con payouts, soporte y comisiones |
| Comercios Estratégicos | Comercios en cuadrante Alto Volumen + Alta Rentabilidad | `COUNT WHERE seg_volumen IN ('mega','grande') AND seg_rent IN ('diamond','platinum','gold')` | > 150 | < 80 | Priorizar asignación de Account Managers; crear programa VIP |

**Query de rendimiento de la cartera de comercios:**
```sql
SELECT
    sm.segmento_volumen,
    sm.segmento_rentabilidad,
    COUNT(DISTINCT m.merchant_id) AS comercios,
    ROUND(SUM(t.monto), 2) AS gmv_total,
    ROUND(SUM(t.ingreso_comision), 2) AS mdr_total,
    ROUND(AVG(t.monto), 2) AS ticket_promedio,
    COUNT(t.transaccion_id) AS total_transacciones
FROM produccion.merchants m
JOIN produccion.segmentacion_merchants sm ON m.merchant_id = sm.merchant_id
JOIN transacciones.transacciones t ON m.merchant_id = t.merchant_id
WHERE t.estado = 'completada'
    AND t.year_month = TO_CHAR(CURRENT_DATE - INTERVAL '1 month', 'YYYY-MM')
GROUP BY sm.segmento_volumen, sm.segmento_rentabilidad
ORDER BY mdr_total DESC;
```

---

## ROL: DIRECTOR DE MARKETING

**Enfoque:** Adquisición de usuarios, retención, activación, efectividad de campañas y costo por comunicación.  
**Frecuencia de revisión:** Semanal / Post-campaña

| KPI | Descripción | Fórmula | Meta | Alerta Roja | Acción sugerida |
|-----|-------------|---------|------|-------------|-----------------|
| MAU (Monthly Active Users) | Usuarios únicos con tx en últimos 30 días | `COUNT(DISTINCT usuario_origen_id) WHERE completada y fecha>=hoy-30` | Crecimiento ≥ 10% MoM | Caída > 3% MoM | Revisar efectividad de campañas de retención |
| Tasa de Activación Nuevos Usuarios | % de nuevos registros con primera tx en 30 días | Ver RN-ACT-001 | > 60% | < 35% | Revisar friction en el proceso de primera transacción |
| Tasa de Reactivación | % de usuarios inactivos que vuelven tras campaña | `reactivados/inactivos_contactados*100` | > 15% | < 5% | Revisar segmentación y oferta de la campaña |
| Open Rate de Email | % de emails abiertos | `AVG(tasa_apertura) WHERE canal='email'` | > 25% | < 15% | Revisar asuntos del email; revisar hora de envío; depurar lista |
| Click Rate de Email | % de emails abiertos con clic | `AVG(tasa_click) WHERE canal='email'` | > 8% | < 3% | Revisar call-to-action; revisar relevancia del contenido |
| Costo por Canal | Costo total por canal de comunicación | `SUM(costo_total) GROUP BY tipo_canal` | Controlado por budget | Costo SMS > 40% del total de notif | Migrar al canal push como alternativa más barata |
| ROI de Campañas | Ingreso incremental / Costo de campaña | Ver ontología: Concepto ROI de Campaña | > 300% ROI | < 100% (no rentable) | Revisar segmento objetivo; pausar campaña si ROI < 100% |
| Tasa de Conversión de Campaña | % de alcanzados que realizaron la acción objetivo | `conversiones/alcanzados*100` | > 3% | < 1% | Revisar relevancia del incentivo y del segmento objetivo |

**Query de efectividad de comunicaciones por canal:**
```sql
SELECT
    tipo_canal,
    COUNT(*) AS envios_totales,
    SUM(cantidad_enviada) AS mensajes_totales,
    ROUND(SUM(costo_total), 2) AS costo_total,
    ROUND(AVG(costo_total / NULLIF(cantidad_enviada, 0)), 4) AS costo_unitario_real,
    ROUND(AVG(tasa_apertura) * 100, 2) AS open_rate_avg_pct,
    ROUND(AVG(tasa_click) * 100, 2) AS click_rate_avg_pct,
    COUNT(CASE WHEN estado = 'entregada' THEN 1 END) AS entregados,
    COUNT(CASE WHEN estado = 'rechazada' THEN 1 END) AS rechazados,
    ROUND(COUNT(CASE WHEN estado = 'entregada' THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) AS tasa_entrega_pct
FROM produccion.notificaciones
WHERE fecha_envio >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY tipo_canal
ORDER BY costo_total DESC;
```

---

## ROL: DIRECTOR DE RIESGO

**Enfoque:** Control del fraude, monitoreo de alertas, protección financiera, cumplimiento regulatorio.  
**Frecuencia de revisión:** Tiempo real (dashboard de alertas) / Diaria

| KPI | Descripción | Fórmula | Meta | Alerta Roja | Acción sugerida |
|-----|-------------|---------|------|-------------|-----------------|
| Tasa de Fraude Global | % de transacciones fraudulentas | `COUNT(flag_fraude=T)/COUNT(total)` | < 0.5% | > 2.5% (nivel IBM dataset) | Revisar modelo de detección; ajustar umbrales de score |
| Monto Fraudulento Mensual | Pérdida absoluta por fraude confirmado | `SUM(monto) WHERE fraude confirmado` | < $50,000/mes | > $200,000/mes | Revisión de urgencia del modelo; posibles ajustes al umbral |
| Alertas Críticas Pendientes | Alertas con score > 0.9 sin resolver | `COUNT(fraude) WHERE score>0.9 AND estado='pendiente'` | 0 | > 5 | Escalar inmediatamente; asignar analistas adicionales |
| Tasa de Falsos Positivos | Alertas que resultaron legítimas tras revisión | `COUNT(descartados)/COUNT(alertas_revisadas)` | < 15% | > 40% | Ajustar umbral del modelo hacia arriba; revisar features |
| Tiempo de Resolución de Alertas | Promedio de horas desde detección hasta resolución | `AVG(fecha_resolucion - fecha_deteccion)` | < SLA por nivel | SLA crítico excedido en > 1 alerta | Reasignar recursos; escalar a gerencia |
| Comercios de Alto Riesgo | Comercios con `estado_riesgo IN ('alerta','suspendido')` | `COUNT(merchant_id) WHERE estado_riesgo IN ('alerta','suspendido')` | < 50 | > 150 | Revisión del portafolio; considerar controles adicionales |
| Score de Riesgo Promedio | Temperatura general de riesgo del portafolio | `AVG(riesgo_score) FROM transacciones` | < 0.15 | > 0.30 | Revisar si hay segmento o comercio con scores elevados |

**Query de dashboard de riesgo diario:**
```sql
SELECT
    DATE(t.fecha_transaccion) AS fecha,
    COUNT(*) AS total_transacciones,
    COUNT(CASE WHEN f.flag_fraude = TRUE THEN 1 END) AS fraudes_detectados,
    ROUND(COUNT(CASE WHEN f.flag_fraude = TRUE THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 4) AS tasa_fraude_pct,
    ROUND(SUM(CASE WHEN f.flag_fraude = TRUE THEN t.monto ELSE 0 END), 2) AS monto_fraudulento,
    ROUND(AVG(t.riesgo_score), 4) AS score_riesgo_promedio,
    COUNT(CASE WHEN f.estado_revision = 'pendiente' THEN 1 END) AS alertas_pendientes,
    COUNT(CASE WHEN f.estado_revision = 'confirmado' THEN 1 END) AS fraudes_confirmados,
    COUNT(CASE WHEN f.estado_revision = 'descartado' THEN 1 END) AS falsos_positivos
FROM transacciones.transacciones t
LEFT JOIN produccion.fraude f ON t.transaccion_id = f.transaccion_id
WHERE t.fecha_transaccion >= CURRENT_DATE - 30
GROUP BY DATE(t.fecha_transaccion)
ORDER BY fecha DESC;
```

---

## CUADRO DE MANDO INTEGRAL — RESUMEN EJECUTIVO

| Perspectiva | KPI Clave | Meta | Responsable |
|-------------|-----------|------|-------------|
| **Crecimiento** | GMV MoM | +10% | CEO / Dir. Comercial |
| **Crecimiento** | Nuevos Comercios Activos | ≥ 42/mes | Dir. Comercial |
| **Crecimiento** | MAU | +10% MoM | Dir. Marketing |
| **Rentabilidad** | Margen Neto Ajustado | ≥ 0.8% del GMV | CFO |
| **Rentabilidad** | MDR Rate Efectivo | 1.80% | CFO |
| **Rentabilidad** | Costo Notificaciones / MDR | < 5% | CFO / Dir. Marketing |
| **Operaciones** | Tasa de Aprobación | ≥ 97% | COO |
| **Operaciones** | Tasa de Éxito Payouts | ≥ 99% | COO |
| **Operaciones** | Tiempo de Activación | ≤ 5 días | COO |
| **Riesgo** | Tasa de Fraude | < 0.5% | Dir. Riesgo |
| **Riesgo** | Alertas Críticas Pendientes | 0 | Dir. Riesgo |
| **Marketing** | Tasa de Reactivación | > 15% | Dir. Marketing |
| **Marketing** | Open Rate Email | > 25% | Dir. Marketing |
