# Documento 07 — Catálogo de Reglas de Negocio
## PayNova S.A. — Reglas Operativas, Financieras y Analíticas

**Versión:** 1.0  
**Propósito:** Documentación formal de todas las reglas que gobiernan el comportamiento del negocio. Fuente canónica para agentes SQL y sistemas RAG.  
**Convención de nomenclatura:** `RN-[DOMINIO]-[NÚMERO]`  
**Referencias cruzadas:** `05_business_ontology.md`, `06_metrics_catalog.md`, `10_agent_knowledge_base.md`

---

## DOMINIO: RENTABILIDAD (RN-FIN)

---

### RN-FIN-001: Cálculo del Ingreso por Transacción (MDR)
**Nombre:** Regla de MDR estándar  
**Descripción:** El ingreso que PayNova obtiene de cada transacción completada es el 1.8% del monto bruto de la transacción. Este porcentaje es fijo y se aplica sobre el monto total sin importar el tipo de comercio, canal o monto específico, salvo acuerdos comerciales especiales documentados.  
**Justificación:** El MDR cubre el costo de procesamiento de la red (0.8%), genera el margen operativo (1.0%) y financia la operación completa de la plataforma.  
**Fórmula:** `ingreso_comision = monto * 0.018`  
**Columna en BD:** `transacciones.transacciones.ingreso_comision`  
**Impacto operativo:** Se aplica automáticamente en el ETL al momento de insertar cada transacción.  
**Impacto analítico:** Los ingresos totales de la empresa se calculan como `SUM(ingreso_comision) WHERE estado = 'completada'`. Nunca usar `monto` directamente para calcular ingresos.  
**Excepciones:** Comercios con MDR negociado diferente tienen `mdr_promedio` documentado en `segmentacion_merchants`. En esos casos, el MDR efectivo puede diferir del estándar.

---

### RN-FIN-002: Cálculo del Costo Operativo por Transacción
**Nombre:** Regla de costo operativo fijo  
**Descripción:** El costo operativo directo de procesar cada transacción es el 0.8% del monto bruto. Incluye fees de red de tarjetas, costos de procesamiento y overhead operativo directo.  
**Fórmula:** `costo_operativo = monto * 0.008`  
**Columna en BD:** `transacciones.transacciones.costo_operativo`  
**Impacto analítico:** El costo total de procesamiento es `SUM(costo_operativo) WHERE estado = 'completada'`.

---

### RN-FIN-003: Cálculo del Margen Bruto por Transacción
**Nombre:** Regla del margen transaccional  
**Descripción:** El margen bruto por transacción es la diferencia entre el MDR cobrado y el costo operativo incurrido. Es una columna GENERATED en la base de datos que se calcula automáticamente.  
**Fórmula:** `margen = ingreso_comision - costo_operativo = monto * (0.018 - 0.008) = monto * 0.010`  
**Columna en BD:** `transacciones.transacciones.margen` (GENERATED ALWAYS AS)  
**Valor típico:** 1.0% del monto de la transacción  
**Impacto analítico:** Para calcular la rentabilidad, siempre usar `SUM(margen)` en lugar de calcular manualmente la diferencia. La columna GENERATED garantiza consistencia.

---

### RN-FIN-004: Cálculo del Monto Neto de Payout
**Nombre:** Regla de neto de liquidación  
**Descripción:** El monto neto que recibe un comercio en cada liquidación es el monto bruto del desembolso menos la comisión de payout, que varía según el segmento de volumen del comercio.  
**Fórmula:** `monto_neto = monto - comision_payout`  
**Tasas de comisión por segmento:**
- Micro: 0.5% del monto bruto
- Pequeño: 0.4%
- Mediano: 0.3%
- Grande: 0.2%
- Mega: 0.1%  
**Columna en BD:** `produccion.payouts.monto_neto` (GENERATED ALWAYS AS)  
**Impacto analítico:** Para reportar cuánto dinero recibieron los comercios, usar `SUM(monto_neto)`. Para el bruto antes de comisión, usar `SUM(monto)`.

---

### RN-FIN-005: Cálculo del Costo Total de Notificación
**Nombre:** Regla de costo de comunicación  
**Descripción:** El costo total de cada envío de notificación es el producto de la cantidad de mensajes enviados por el costo unitario del canal. Es una columna GENERATED.  
**Fórmula:** `costo_total = cantidad_enviada * costo_unitario`  
**Columna en BD:** `produccion.notificaciones.costo_total` (GENERATED ALWAYS AS)  
**Costos unitarios de referencia:** email=$0.001, sms=$0.05, push=$0.0001, whatsapp=$0.03, webhook=$0.0005  
**Impacto analítico:** El costo total de comunicaciones es `SUM(costo_total) FROM produccion.notificaciones`.

---

### RN-FIN-006: Margen Neto Ajustado (Waterfall de Rentabilidad)
**Nombre:** Regla del margen neto completo  
**Descripción:** El margen neto real del negocio descuenta del margen bruto transaccional los costos de notificación y otros costos operativos no transaccionales.  
**Fórmula:** `Margen Neto = SUM(margen) - SUM(notificaciones.costo_total) - otros_costos_fijos`  
**Impacto analítico:** Usado en el waterfall chart del dashboard para mostrar la contribución de cada componente al margen final. El `SUM(margen)` de transacciones es el punto de partida, no el resultado final.

---

## DOMINIO: ACTIVACIÓN (RN-ACT)

---

### RN-ACT-001: Definición de Usuario Activo
**Nombre:** Regla de actividad de usuario  
**Descripción:** Un usuario se considera activo si ha realizado al menos una transacción con estado `completada` en los últimos 30 días calendario.  
**Fórmula:** `EXISTS (SELECT 1 FROM transacciones.transacciones WHERE usuario_origen_id = u.usuario_id AND estado = 'completada' AND fecha_transaccion >= CURRENT_DATE - 30)`  
**Impacto operativo:** Determina si un usuario recibe comunicaciones de retención o reactivación.  
**Impacto analítico:** La métrica MAU y todos los análisis de "usuarios activos" usan esta definición. No confundir `estado = 'activo'` en `produccion.usuarios` (estado del ciclo de vida) con la condición de actividad transaccional.  
**Nota crítica para agentes:** El campo `produccion.usuarios.estado = 'activo'` NO significa que el usuario haya transaccionado recientemente. Para verificar actividad real, siempre consultar `transacciones.transacciones`.

---

### RN-ACT-002: Clasificación por Inactividad
**Nombre:** Regla de umbrales de inactividad  
**Descripción:** Los usuarios se clasifican en estados de inactividad según el número de días transcurridos desde su última transacción completada.  
**Umbrales:**
- 0–30 días → Activo
- 31–59 días → En riesgo (primer nivel)
- 60–89 días → En riesgo (segundo nivel, requiere campaña)
- 90–179 días → Inactivo (elegible para campaña de reactivación)
- 180+ días → Abandonado (bajo potencial de retorno)  
**Impacto operativo:** Dispara campañas automáticas según el umbral cruzado.  
**Impacto analítico:** Segmentar la base de usuarios por días desde última transacción para análisis de churn.

---

### RN-ACT-003: Definición de Comercio Activo
**Nombre:** Regla de actividad de comercio  
**Descripción:** Un comercio se considera activo si tiene `status_operacional = 'activo'` Y `ultima_actividad >= CURRENT_DATE - 30`.  
**Fórmula:** `merchants.status_operacional = 'activo' AND merchants.ultima_actividad >= CURRENT_DATE - 30`  
**Nota:** `ultima_actividad` se actualiza por el ETL con la fecha de la última transacción procesada por ese comercio.  
**Impacto analítico:** Los KPIs de "comercios activos" y el funnel operativo usan esta definición.

---

### RN-ACT-004: Definición de Usuario Reactivado
**Nombre:** Regla de reactivación de usuario  
**Descripción:** Un usuario se considera reactivado cuando realiza una transacción exitosa habiendo estado previamente inactivo por ≥ 90 días consecutivos. El evento de reactivación es la primera transacción después del período de inactividad.  
**Condición:** `días_desde_última_tx_previa >= 90 AND estado_actual = 'completada'`  
**Impacto analítico:** Permite calcular la tasa de reactivación y el ROI de campañas de win-back.

---

### RN-ACT-005: Definición de Comercio Integrado
**Nombre:** Regla de integración exitosa de comercio  
**Descripción:** Un comercio se considera integrado cuando su registro en `integraciones_merchant` tiene `estado_integracion = 'activa'` Y `api_key_validado = TRUE`.  
**Impacto analítico:** La segunda etapa del funnel de comercios. Un comercio integrado no es necesariamente activo (puede no haber procesado transacciones aún).

---

## DOMINIO: RIESGO (RN-RIS)

---

### RN-RIS-001: Clasificación de Nivel de Riesgo de Usuario
**Nombre:** Regla de clasificación de riesgo por fraude  
**Descripción:** El nivel de riesgo de un usuario se calcula como el porcentaje de sus transacciones históricas que han sido marcadas con `flag_fraude = TRUE`.  
**Fórmula:**
- `bajo`: pct_fraude < 1%
- `medio`: pct_fraude entre 1% y 5%
- `alto`: pct_fraude entre 5% y 15%
- `critico`: pct_fraude ≥ 15%  
**Columna en BD:** `produccion.usuarios.nivel_riesgo`  
**Impacto operativo:** Los usuarios con nivel `critico` son candidatos a suspensión automática.  
**Impacto analítico:** Siempre filtrar por `nivel_riesgo` cuando el análisis requiera excluir usuarios fraudulentos.

---

### RN-RIS-002: Umbrales de Score de Riesgo para Alertas
**Nombre:** Regla de umbrales de riesgo transaccional  
**Descripción:** El sistema actúa diferente según el riesgo_score calculado por el modelo de detección de fraude.  
**Umbrales y acciones:**
- 0.00 – 0.30: Sin acción. Procesamiento normal.
- 0.31 – 0.50: Monitoreo pasivo. Sin bloqueo.
- 0.51 – 0.70: Crear alerta en `produccion.fraude` con `estado_revision = 'pendiente'`. SLA: 48h.
- 0.71 – 0.90: Alerta prioritaria. SLA: 4h. Notificación al equipo de riesgo.
- 0.91 – 1.00: Bloqueo automático de la transacción. SLA: 1h para revisión.  
**Impacto analítico:** El campo `riesgo_score` en `transacciones.transacciones` determina si existe una alerta. Para análisis de fraude de alta certeza, usar `fraude.flag_fraude = TRUE AND estado_revision = 'confirmado'`.

---

### RN-RIS-003: Suspensión Automática de Comercio
**Nombre:** Regla de suspensión por fraude sistémico  
**Descripción:** Un comercio es suspendido automáticamente si se detectan 3 o más alertas de fraude confirmadas en un período de 30 días, o si el monto fraudulento acumulado supera el 10% del GMV del mes.  
**Condición:** `COUNT(fraudes confirmados en 30d) >= 3 OR (monto_fraudulento / gmv_mes) >= 0.10`  
**Acción:** `UPDATE merchants SET status_operacional = 'suspendido'`  
**Impacto analítico:** Los comercios suspendidos no aparecen en métricas de "comercios activos".

---

### RN-RIS-004: Escalamiento de Alertas de Fraude
**Nombre:** Regla de escalamiento por SLA  
**Descripción:** Las alertas de fraude que no son revisadas dentro de su SLA definido se escalan automáticamente al siguiente nivel de responsabilidad.  
**Proceso:**
- Nivel 1 (analista junior): SLA 48h → escalado a nivel 2 si no se resuelve
- Nivel 2 (analista senior): SLA 4h → escalado a gerencia si no se resuelve
- Nivel 3 (gerencia de riesgo): SLA 1h  
**Estado en BD:** Alerta escalada tiene `estado_revision = 'escalado'`

---

### RN-RIS-005: Clasificación del Estado de Riesgo de Comercio
**Nombre:** Regla de estado de riesgo del comercio  
**Descripción:** El campo `estado_riesgo` en `segmentacion_merchants` refleja la situación actual del comercio respecto a eventos de riesgo.  
**Valores:**
- `normal`: Sin alertas activas. Operación estándar.
- `monitoreado`: 1 alerta activa no confirmada. Revisión en curso.
- `alerta`: Alerta confirmada o múltiples alertas activas. Comercio bajo escrutinio.
- `suspendido`: Operación suspendida por decisión del equipo de riesgo.  
**Impacto analítico:** Filtrar `estado_riesgo != 'suspendido'` para análisis de comercios operativos.

---

## DOMINIO: MARKETING (RN-MKT)

---

### RN-MKT-001: Regla de Atribución de Campañas
**Nombre:** Regla de atribución last-touch  
**Descripción:** Las conversiones se atribuyen a la última campaña con la que el usuario interactuó (abrió o hizo clic) dentro de una ventana de 72 horas previas a la conversión.  
**Ventana de atribución:** 72 horas desde el último engagement  
**Condición de atribución:** `fecha_conversion - fecha_ultimo_engagement <= 72 HORAS`  
**Tipos de engagement válidos:** Email abierto, email click, SMS click, push click  
**Conversiones orgánicas:** Si el usuario convierte sin engagement reciente → no se atribuye a ninguna campaña.  
**Impacto analítico:** No sumar conversiones de múltiples campañas para el mismo usuario en la misma ventana. Si dos campañas coinciden, gana la más reciente.

---

### RN-MKT-002: Regla de Elegibilidad para Campaña
**Nombre:** Regla de exclusión de campaña  
**Descripción:** Un usuario NO debe incluirse en una campaña si cumple alguno de los siguientes criterios:
1. Estado `suspendido` o `bloqueado` en `produccion.usuarios`
2. `nivel_riesgo = 'critico'`
3. Recibió una comunicación de la misma campaña en las últimas 48 horas (anti-spam)
4. Se dio de baja (opt-out) del canal en cuestión  
**Impacto operativo:** El sistema de envío de campañas debe aplicar estos filtros antes de generar el lote de notificaciones.

---

### RN-MKT-003: Regla de Incrementalidad
**Nombre:** Regla de medición de impacto incremental  
**Descripción:** Para medir el impacto real de una campaña, se requiere un grupo de control (usuarios elegibles que NO recibieron la campaña) de al menos el 10% del segmento objetivo.  
**Fórmula de Lift:** `Lift = (Tasa conversión tratados - Tasa conversión control) / Tasa conversión control * 100`  
**Fórmula Incrementalidad:** `Conversiones incrementales = (Tasa tratados - Tasa control) * Total usuarios tratados`  
**Impacto analítico:** Sin grupo de control, no es posible calcular incrementalidad. La tasa de conversión bruta sobreestima el impacto real.

---

### RN-MKT-004: Regla de Canibalización
**Nombre:** Indicador de canibalización de campaña  
**Descripción:** Una campaña se considera canibalizante si la tasa de conversión del grupo de control (usuarios que habrían transaccionado de todos modos) es mayor al 50% de la tasa de conversión del grupo tratado.  
**Indicador:** `Tasa_control / Tasa_tratados >= 0.50`  
**Impacto analítico:** Cuando hay alta canibalización, el ROI real de la campaña es mucho menor que el ROI aparente. Reportar siempre el ROI incremental, no el bruto.

---

## DOMINIO: OPERACIONES (RN-OPS)

---

### RN-OPS-001: Elegibilidad de Comercio para Payout
**Nombre:** Regla de elegibilidad para liquidación  
**Descripción:** Un comercio solo puede recibir un payout si cumple TODAS las condiciones simultáneamente:
1. `merchants.status_operacional = 'activo'`
2. `integraciones_merchant.estado_integracion = 'activa'`
3. Cuenta bancaria validada (campo interno no expuesto en BD actual)
4. Sin alertas de fraude `critico` activas y no resueltas
5. GMV acumulado en el período > $0
6. No tiene un payout en estado `pendiente_revision` del período anterior  
**Impacto operativo:** El proceso batch de generación de payouts evalúa estas condiciones antes de crear cada registro.  
**Impacto analítico:** Si se reportan comercios sin payouts en el período, verificar estas condiciones antes de asumir que no generaron actividad.

---

### RN-OPS-002: Frecuencia de Liquidación por Segmento
**Nombre:** Regla de ciclo de liquidación  
**Descripción:** La frecuencia de liquidación a los comercios varía según su segmento de volumen.  
**Frecuencias:**
- Micro y Pequeño: Semanal (lunes de la semana siguiente al período)
- Mediano: Bisemanal
- Grande: Diaria (día siguiente de cada transacción)
- Mega: Diaria con liquidación intradiaria opcional  
**Impacto analítico:** Para comparar payouts entre segmentos, normalizar siempre por período mensual y no por número de payouts.

---

### RN-OPS-003: Regla de Comercio con Notificaciones
**Nombre:** Definición de comercio con notificaciones activas  
**Descripción:** Un comercio tiene notificaciones activas si tiene al menos uno de los siguientes canales habilitados en `integraciones_merchant`:
- `email_integrado = TRUE`, o
- `sms_integrado = TRUE`  
**Uso en funnel:** Esta es la cuarta etapa del funnel de comercios.  
**Impacto analítico:** Un comercio puede estar activo transaccionalmente sin tener notificaciones habilitadas. Son dos dimensiones independientes.

---

## DOMINIO: SEGMENTACIÓN (RN-SEG)

---

### RN-SEG-001: Segmentación de Usuarios por Actividad (RFM)
**Nombre:** Regla de segmento transaccional de usuarios  
**Descripción:** Los usuarios se clasifican en segmentos de actividad según su posición en la distribución de número de transacciones.  
**Regla:**
- P75 o superior → `alto_volumen`
- P50 a P75 → `frecuente`
- P25 a P50 → `esporadico`
- Menos de P25 o sin tx en 90d → `inactivo`  
**Columna en BD:** `produccion.segmentacion.segmento_transaccional`  
**Impacto analítico:** Los percentiles se recalculan mensualmente, por lo que un usuario puede cambiar de segmento entre períodos.

---

### RN-SEG-002: Segmentación de Usuarios por Rentabilidad
**Nombre:** Regla de segmento de rentabilidad de usuarios  
**Descripción:** Se clasifica a los usuarios según su `score_rentabilidad` calculado sobre el volumen monetario histórico.  
**Regla:**
- `score_rentabilidad > 80` → `platinum`
- `score_rentabilidad 60–80` → `gold`
- `score_rentabilidad 40–60` → `silver`
- `score_rentabilidad < 40` → `bronze`  
**Columna en BD:** `produccion.segmentacion.segmento_rentabilidad`

---

### RN-SEG-003: Segmentación de Comercios por Volumen
**Nombre:** Regla de segmento de volumen de comercios  
**Descripción:** Los comercios se clasifican por su GMV mensual promedio de los últimos 3 meses.  
**Regla:**
- GMV mensual > $1,000,000 → `mega`
- $200,000 – $1,000,000 → `grande`
- $50,000 – $200,000 → `mediano`
- $10,000 – $50,000 → `pequeno`
- < $10,000 → `micro`  
**Columna en BD:** `produccion.segmentacion_merchants.segmento_volumen`  
**Impacto analítico:** Si un agente pregunta por "comercios grandes", interpretar como `segmento_volumen IN ('grande', 'mega')`.

---

### RN-SEG-004: Segmentación de Comercios por Rentabilidad
**Nombre:** Regla de segmento de rentabilidad de comercios  
**Descripción:** Los comercios se clasifican por el MDR neto mensual generado en los últimos 3 meses.  
**Regla:**
- MDR mensual > $25,000 → `diamond`
- $8,000 – $25,000 → `platinum`
- $2,000 – $8,000 → `gold`
- $500 – $2,000 → `silver`
- < $500 → `bronze`  
**Columna en BD:** `produccion.segmentacion_merchants.segmento_rentabilidad`

---

### RN-SEG-005: Recálculo Periódico de Segmentación
**Nombre:** Regla de vigencia de segmentación  
**Descripción:** Los segmentos de usuarios y comercios se recalculan mensualmente. Una segmentación tiene vigencia de máximo 35 días. Si `fecha_segmentacion < CURRENT_DATE - 35`, los datos de segmentación se consideran desactualizados.  
**Impacto analítico:** Siempre verificar `fecha_segmentacion` al hacer análisis de segmentación. Si está desactualizada, calcular el segmento directamente desde `transacciones.transacciones`.
