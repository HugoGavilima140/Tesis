# Documento 06 — Catálogo de Métricas
## PayNova S.A. — Definiciones Operativas y Analíticas

**Versión:** 1.0  
**Propósito:** Fuente canónica de definición de métricas para dashboards, reportes, agentes SQL y sistemas RAG.  
**Referencias cruzadas:** `05_business_ontology.md`, `07_business_rules.md`, `08_executive_kpis.md`

---

## CATEGORÍA: CRECIMIENTO

---

### Métrica: Usuarios Registrados
**Descripción:** Número total de usuarios que han completado el proceso de registro en la plataforma, independientemente de si han realizado alguna transacción.  
**Fórmula:** `COUNT(DISTINCT usuario_id) FROM produccion.usuarios WHERE estado NOT IN ('bloqueado')`  
**Interpretación:** Mide el tamaño total de la base de usuarios potenciales. Por sí sola no refleja engagement.  
**Granularidad:** Total, mensual, por período de cohorte  
**Frecuencia:** Diaria  
**Tablas requeridas:** `produccion.usuarios`  
**Casos de uso:** Tracking de crecimiento bruto, funnel de adquisición, comparación YoY

---

### Métrica: Usuarios Activos Mensuales (MAU)
**Descripción:** Número de usuarios distintos que realizaron al menos una transacción completada en los últimos 30 días.  
**Fórmula:** `COUNT(DISTINCT usuario_origen_id) FROM transacciones.transacciones WHERE estado = 'completada' AND fecha_transaccion >= CURRENT_DATE - 30`  
**Interpretación:** Indicador clave de engagement real. Un MAU creciente indica salud del negocio.  
**Granularidad:** Mensual, semanal  
**Frecuencia:** Diaria (con ventana móvil de 30 días)  
**Tablas requeridas:** `transacciones.transacciones`  
**Casos de uso:** KPI ejecutivo principal, benchmarking de crecimiento

---

### Métrica: Nuevos Usuarios por Período
**Descripción:** Número de usuarios registrados por primera vez en un período específico.  
**Fórmula:** `COUNT(usuario_id) FROM produccion.usuarios WHERE fecha_registro BETWEEN fecha_inicio AND fecha_fin`  
**Interpretación:** Mide la efectividad de estrategias de adquisición. Debe compararse con el CAC.  
**Granularidad:** Diaria, semanal, mensual  
**Frecuencia:** Diaria  
**Tablas requeridas:** `produccion.usuarios`

---

### Métrica: Comercios Activos
**Descripción:** Número de comercios con `status_operacional = 'activo'` que han procesado al menos una transacción en los últimos 30 días.  
**Fórmula:** `COUNT(DISTINCT m.merchant_id) FROM produccion.merchants m JOIN transacciones.transacciones t ON m.merchant_id = t.merchant_id WHERE m.status_operacional = 'activo' AND t.fecha_transaccion >= CURRENT_DATE - 30 AND t.estado = 'completada'`  
**Interpretación:** Mide la red activa de comercios. Crítico para el modelo de negocio de plataforma.  
**Granularidad:** Total, por segmento, por región, por categoría MCC  
**Frecuencia:** Diaria  
**Tablas requeridas:** `produccion.merchants`, `transacciones.transacciones`

---

### Métrica: Nuevos Comercios Activos
**Descripción:** Comercios que completaron su primera transacción exitosa en el período de análisis.  
**Fórmula:** `COUNT(DISTINCT merchant_id) FROM transacciones.transacciones WHERE fecha_transaccion BETWEEN inicio AND fin AND estado = 'completada' AND merchant_id NOT IN (SELECT DISTINCT merchant_id FROM transacciones.transacciones WHERE fecha_transaccion < inicio)`  
**Interpretación:** Mide la efectividad del proceso de onboarding y ventas B2B.  
**Frecuencia:** Mensual  
**Meta PayNova:** +500 comercios nuevos por año (~42 por mes)

---

### Métrica: Tasa de Activación de Usuarios (30 días)
**Descripción:** Porcentaje de usuarios recién registrados que realizaron al menos una transacción dentro de sus primeros 30 días en la plataforma.  
**Fórmula:** `COUNT(usuarios con tx en primeros 30d) / COUNT(usuarios registrados en el período) * 100`  
**Interpretación:** Mide la efectividad del proceso de onboarding de usuarios. < 40% indica fricción en el primer uso.  
**Granularidad:** Por cohorte de registro  
**Frecuencia:** Semanal  
**Meta PayNova:** > 60%  
**Tablas requeridas:** `produccion.usuarios`, `transacciones.transacciones`

---

## CATEGORÍA: TRANSACCIONES

---

### Métrica: Número de Transacciones
**Descripción:** Conteo total de transacciones en un período, por estado definido.  
**Fórmula (todas):** `COUNT(transaccion_id) FROM transacciones.transacciones WHERE fecha_transaccion BETWEEN inicio AND fin`  
**Fórmula (completadas):** Agregar `AND estado = 'completada'`  
**Granularidad:** Diaria, horaria, por canal, por tipo, por comercio, por segmento  
**Frecuencia:** Tiempo real (acumulado en dashboard)  
**Tablas requeridas:** `transacciones.transacciones`

---

### Métrica: GMV (Gross Merchandise Volume)
**Descripción:** Suma total del monto bruto de todas las transacciones completadas. Principal indicador de escala del negocio.  
**Fórmula:** `SUM(monto) FROM transacciones.transacciones WHERE estado = 'completada' AND fecha_transaccion BETWEEN inicio AND fin`  
**Interpretación:** Cuánto dinero total fluyó a través de la plataforma. No es ingreso — los ingresos son el ~1.8% del GMV.  
**Granularidad:** Total, mensual, por comercio, por segmento, por canal, por tipo  
**Frecuencia:** Tiempo real / Diaria  
**Tablas requeridas:** `transacciones.transacciones`  
**Casos de uso:** Benchmark de tamaño, comparación YoY, tracking de objetivos  
**Fórmula variante (por comercio):** `SUM(monto) GROUP BY merchant_id`

---

### Métrica: Ticket Promedio (AOV)
**Descripción:** Monto promedio por transacción completada. Refleja el valor típico de las compras procesadas.  
**Fórmula:** `AVG(monto) FROM transacciones.transacciones WHERE estado = 'completada'`  
**Interpretación:** Un ticket promedio creciente puede indicar penetración en comercios de mayor valor o cambio en el mix de categorías.  
**Granularidad:** Total, por comercio, por canal, por categoría MCC, por segmento de usuario  
**Frecuencia:** Diaria  
**Tablas requeridas:** `transacciones.transacciones`

---

### Métrica: Tasa de Aprobación
**Descripción:** Porcentaje de transacciones intentadas que fueron aprobadas exitosamente.  
**Fórmula:** `COUNT(estado='completada') / COUNT(*) * 100 FROM transacciones.transacciones`  
**Interpretación:** < 95% es señal de alerta. Puede deberse a problemas técnicos, fraude elevado o problemas con la red de tarjetas.  
**Granularidad:** Total, por canal, por tipo, por hora, por comercio  
**Frecuencia:** Tiempo real  
**Meta PayNova:** ≥ 97%  
**Tablas requeridas:** `transacciones.transacciones`  
**Casos de uso:** Monitoreo operativo, heatmap de rechazos, salud del sistema

---

### Métrica: Tasa de Rechazo
**Descripción:** Complemento de la tasa de aprobación. Porcentaje de transacciones que terminaron en estado rechazada o error.  
**Fórmula:** `COUNT(estado IN ('rechazada','error')) / COUNT(*) * 100`  
**Interpretación:** Alta tasa de rechazo en horarios específicos puede indicar problemas técnicos. Alta tasa por `monto_inusual` puede indicar fraude.  
**Granularidad:** Por hora del día (`hora_transaccion`), por día de semana (`dia_semana`), por canal, por comercio  
**Tablas requeridas:** `transacciones.transacciones`  
**Casos de uso:** Heatmap operativo, análisis de causas raíz

---

### Métrica: Transacciones por Usuario Activo (ARPU de transacciones)
**Descripción:** Número promedio de transacciones realizadas por usuario activo en el período.  
**Fórmula:** `COUNT(transacciones) / COUNT(DISTINCT usuario_origen_id) WHERE estado = 'completada'`  
**Interpretación:** Indicador de frecuencia de uso. Un valor bajo puede indicar oportunidad de engagement.  
**Granularidad:** Mensual, por segmento de usuario  
**Tablas requeridas:** `transacciones.transacciones`

---

## CATEGORÍA: RENTABILIDAD

---

### Métrica: Ingresos Totales (MDR Total)
**Descripción:** Suma total de las comisiones MDR generadas por todas las transacciones completadas en el período.  
**Fórmula:** `SUM(ingreso_comision) FROM transacciones.transacciones WHERE estado = 'completada'`  
**Valor típico:** ~1.8% del GMV  
**Granularidad:** Total, mensual, por comercio, por categoría  
**Tablas requeridas:** `transacciones.transacciones`

---

### Métrica: Costos Operativos Totales
**Descripción:** Suma total de los costos de procesamiento de todas las transacciones completadas.  
**Fórmula:** `SUM(costo_operativo) FROM transacciones.transacciones WHERE estado = 'completada'`  
**Valor típico:** ~0.8% del GMV  
**Tablas requeridas:** `transacciones.transacciones`

---

### Métrica: Margen Bruto Transaccional
**Descripción:** Diferencia entre ingresos por MDR y costos operativos directos de las transacciones.  
**Fórmula:** `SUM(margen) FROM transacciones.transacciones WHERE estado = 'completada'`  
**Equivalente:** `SUM(ingreso_comision) - SUM(costo_operativo)`  
**Valor típico:** ~1.0% del GMV  
**Tablas requeridas:** `transacciones.transacciones`

---

### Métrica: Margen Neto Ajustado
**Descripción:** Margen bruto transaccional menos costos adicionales de comunicación y operación no transaccional.  
**Fórmula:** `SUM(margen) - SUM(notificaciones.costo_total) - otros_costos`  
**Tablas requeridas:** `transacciones.transacciones`, `produccion.notificaciones`

---

### Métrica: Rentabilidad por Comercio
**Descripción:** MDR neto generado por un comercio específico en el período, después de descontar costos de notificación atribuibles.  
**Fórmula:** `SUM(t.margen) - SUM(n.costo_total) GROUP BY t.merchant_id`  
**Granularidad:** Por comercio, por segmento  
**Tablas requeridas:** `transacciones.transacciones`, `produccion.notificaciones`  
**Casos de uso:** Matriz estratégica, priorización de Account Managers

---

### Métrica: MDR Rate Efectivo
**Descripción:** Tasa MDR promedio efectiva cobrada a un comercio, que puede diferir del MDR estándar por negociaciones o excepciones.  
**Fórmula:** `SUM(ingreso_comision) / SUM(monto) * 100 GROUP BY merchant_id`  
**Interpretación:** Si el MDR rate efectivo < 1.8%, el comercio tiene condiciones especiales negociadas.  
**Tablas requeridas:** `transacciones.transacciones`

---

### Métrica: Costo de Notificaciones por Comercio
**Descripción:** Gasto total en comunicaciones atribuido a un comercio en el período.  
**Fórmula:** `SUM(costo_total) FROM produccion.notificaciones GROUP BY merchant_id`  
**Granularidad:** Por comercio, por canal, por período  
**Tablas requeridas:** `produccion.notificaciones`  
**Casos de uso:** Pareto de comercios costosos, optimización de canales

---

## CATEGORÍA: MARKETING

---

### Métrica: Tasa de Conversión de Campaña
**Descripción:** Porcentaje de usuarios alcanzados por una campaña que realizaron la acción objetivo dentro de la ventana de atribución.  
**Fórmula:** `COUNT(usuarios que convirtieron) / COUNT(usuarios alcanzados por la campaña) * 100`  
**Tablas requeridas:** `produccion.campanas`, `produccion.notificaciones`, `transacciones.transacciones`  
**Benchmark típico:** > 3%

---

### Métrica: Open Rate (Email)
**Descripción:** Porcentaje de emails entregados que fueron abiertos por el destinatario.  
**Fórmula:** `AVG(tasa_apertura) FROM produccion.notificaciones WHERE tipo_canal = 'email' AND estado = 'entregada'`  
**Benchmark PayNova:** > 25%  
**Tablas requeridas:** `produccion.notificaciones`

---

### Métrica: Click Rate (Email)
**Descripción:** Porcentaje de emails abiertos donde el destinatario hizo clic en un enlace.  
**Fórmula:** `AVG(tasa_click) FROM produccion.notificaciones WHERE tipo_canal = 'email'`  
**Benchmark PayNova:** > 8%  
**Tablas requeridas:** `produccion.notificaciones`

---

### Métrica: Costo por Notificación Enviada
**Descripción:** Costo promedio de cada mensaje enviado, agregado por canal.  
**Fórmula:** `SUM(costo_total) / SUM(cantidad_enviada) GROUP BY tipo_canal`  
**Tablas requeridas:** `produccion.notificaciones`

---

### Métrica: Costo Total de Notificaciones
**Descripción:** Gasto total en comunicaciones en el período, sumando todos los canales.  
**Fórmula:** `SUM(costo_total) FROM produccion.notificaciones WHERE fecha_envio BETWEEN inicio AND fin`  
**Tablas requeridas:** `produccion.notificaciones`

---

## CATEGORÍA: OPERACIONES

---

### Métrica: Tiempo de Activación de Comercio
**Descripción:** Días transcurridos entre la fecha de inicio del onboarding y la primera transacción exitosa del comercio.  
**Fórmula:** `AVG(MIN(t.fecha_transaccion) - i.fecha_inicio) FROM integraciones_merchant i JOIN transacciones t ON i.merchant_id = t.merchant_id GROUP BY i.merchant_id`  
**SLA estándar:** ≤ 5 días hábiles  
**Tablas requeridas:** `produccion.integraciones_merchant`, `transacciones.transacciones`

---

### Métrica: Tasa de Éxito de Payouts
**Descripción:** Porcentaje de payouts iniciados que fueron procesados exitosamente.  
**Fórmula:** `COUNT(estado='procesado') / COUNT(*) * 100 FROM produccion.payouts`  
**Meta PayNova:** ≥ 99%  
**Tablas requeridas:** `produccion.payouts`  
**Casos de uso:** KPI del gauge en dashboard ejecutivo

---

### Métrica: Monto Total Desembolsado
**Descripción:** Suma del monto neto de todos los payouts procesados exitosamente en el período.  
**Fórmula:** `SUM(monto_neto) FROM produccion.payouts WHERE estado = 'procesado' AND fecha_payout BETWEEN inicio AND fin`  
**Tablas requeridas:** `produccion.payouts`

---

### Métrica: Promedio de Payouts por Comercio
**Descripción:** Monto neto promedio desembolsado por comercio activo en el período.  
**Fórmula:** `SUM(monto_neto) / COUNT(DISTINCT merchant_id) FROM produccion.payouts WHERE estado = 'procesado'`  
**Tablas requeridas:** `produccion.payouts`

---

### Métrica: Funnel de Conversión de Comercios
**Descripción:** Tasa de conversión entre cada etapa del funnel de onboarding de comercios.  
**Fórmulas por etapa:**
- Conv. Registrados → Integrados: `comercios_integrados / comercios_registrados`
- Conv. Integrados → Activos: `comercios_activos / comercios_integrados`
- Conv. Activos → Con Notificaciones: `comercios_con_notif / comercios_activos`
- Conv. Con Notif → Con Transacciones: `comercios_con_tx / comercios_con_notif`
- Conv. Con Tx → Con Payouts: `comercios_con_payouts / comercios_con_tx`  
**Tablas requeridas:** `produccion.vw_funnel_comercios`

---

## CATEGORÍA: RIESGO

---

### Métrica: Tasa de Fraude
**Descripción:** Porcentaje de transacciones marcadas como fraudulentas (flag_fraude = TRUE) sobre el total de transacciones procesadas.  
**Fórmula:** `COUNT(flag_fraude=TRUE) / COUNT(total_transacciones) * 100`  
**Umbral de alerta PayNova:** > 0.5%  
**Tasa típica en dataset IBM:** ~2.5%  
**Tablas requeridas:** `produccion.fraude`, `transacciones.transacciones`

---

### Métrica: Monto Fraudulento
**Descripción:** Suma total del monto de transacciones confirmadas como fraudulentas.  
**Fórmula:** `SUM(t.monto) FROM transacciones t JOIN fraude f ON t.transaccion_id = f.transaccion_id WHERE f.flag_fraude = TRUE AND f.estado_revision = 'confirmado'`  
**Tablas requeridas:** `produccion.fraude`, `transacciones.transacciones`

---

### Métrica: Casos de Fraude Confirmados
**Descripción:** Número de alertas de fraude que tras revisión manual fueron confirmadas como fraudes reales.  
**Fórmula:** `COUNT(fraude_id) FROM produccion.fraude WHERE estado_revision = 'confirmado'`  
**Tablas requeridas:** `produccion.fraude`

---

### Métrica: Tasa de Falsos Positivos
**Descripción:** Porcentaje de alertas de fraude que tras revisión resultaron ser transacciones legítimas incorrectamente alertadas.  
**Fórmula:** `COUNT(estado_revision='descartado') / COUNT(total_alertas) * 100`  
**Interpretación:** Alta tasa de falsos positivos indica que el modelo es demasiado agresivo, impactando la experiencia del usuario.  
**Tablas requeridas:** `produccion.fraude`

---

### Métrica: Score de Riesgo Promedio
**Descripción:** Promedio del score de riesgo de todas las transacciones en el período. Monitorea si la calidad de la cartera está cambiando.  
**Fórmula:** `AVG(riesgo_score) FROM transacciones.transacciones WHERE fecha_transaccion BETWEEN inicio AND fin`  
**Tablas requeridas:** `transacciones.transacciones`
