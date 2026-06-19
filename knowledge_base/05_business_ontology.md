# Documento 05 — Ontología Empresarial
## PayNova S.A. — Vocabulario Canónico de Negocio

**Versión:** 1.0  
**Propósito:** Definición formal de todos los conceptos de negocio para uso en sistemas RAG, agentes SQL y benchmarks de evaluación.  
**Referencias cruzadas:** `04_data_dictionary.md`, `06_metrics_catalog.md`, `07_business_rules.md`

---

## DOMINIO: USUARIOS

---

### Concepto: Cliente Activo
**Definición:** Usuario que ha realizado al menos una transacción en los últimos 30 días calendario desde la fecha de análisis.  
**Sinónimos:** Usuario activo, cliente recurrente, usuario en uso  
**Conceptos relacionados:** Cliente inactivo, tasa de retención, churn, score de actividad  
**Fórmula de clasificación:** `MAX(fecha_transaccion) >= CURRENT_DATE - 30`  
**Tabla principal:** `transacciones.transacciones`, `produccion.usuarios`  
**Métricas relacionadas:** DAU (Daily Active Users), MAU (Monthly Active Users), Tasa de Retención  
**Reglas relacionadas:** `RN-ACT-001` (Definición de usuario activo)

---

### Concepto: Cliente Inactivo
**Definición:** Usuario que tenía historial de transacciones pero no ha realizado ninguna en un período mayor a 90 días.  
**Sinónimos:** Usuario dormido, cliente en riesgo de churn, usuario desenganchado  
**Conceptos relacionados:** Reactivación, churn, campaña de win-back  
**Umbral:** Sin transacciones entre 90 y 179 días  
**Tabla principal:** `produccion.usuarios` (estado calculado)  
**Métricas relacionadas:** Tasa de churn, tasa de reactivación  
**Reglas relacionadas:** `RN-ACT-002` (Clasificación por inactividad)

---

### Concepto: Usuario Premium
**Definición:** Usuario clasificado en el segmento de rentabilidad "Platinum" con score_rentabilidad > 80 y al menos 12 transacciones en el año.  
**Sinónimos:** Cliente VIP, usuario de alto valor, cliente estratégico  
**Conceptos relacionados:** Score de rentabilidad, LTV (Lifetime Value), segmento Platinum  
**Tabla principal:** `produccion.usuarios`, `produccion.segmentacion`  
**Métricas relacionadas:** LTV, GMV por usuario, MDR por usuario  
**Reglas relacionadas:** `RN-SEG-001` (Criterios de segmentación de usuarios)

---

### Concepto: Usuario de Alto Valor (High-Value User)
**Definición:** Usuario cuyo volumen monetario transaccionado (GMV personal) se encuentra en el percentil 90 o superior del total de usuarios activos.  
**Sinónimos:** Heavy user, usuario whale, cliente premium  
**Conceptos relacionados:** Segmento Platinum, score_rentabilidad, LTV  
**Umbral típico:** GMV personal > $5,000 en los últimos 12 meses  
**Tabla principal:** `transacciones.transacciones` (agrupado por usuario_origen_id)  
**Métricas relacionadas:** GMV por usuario, ticket promedio, frecuencia

---

### Concepto: Usuario en Riesgo de Abandono (Churn Risk)
**Definición:** Usuario activo cuya frecuencia transaccional ha disminuido más de un 50% en el último mes comparado con su promedio histórico, o que lleva entre 31 y 89 días sin realizar transacciones.  
**Sinónimos:** Usuario en riesgo, cliente en churning, usuario desenganchado  
**Conceptos relacionados:** Churn, reactivación, propensión al abandono  
**Tabla principal:** `transacciones.transacciones`, `produccion.usuarios`  
**Métricas relacionadas:** Probabilidad de churn, días sin actividad  
**Acción recomendada:** Activar campaña de retención con incentivo personalizado

---

### Concepto: Score de Actividad
**Definición:** Puntuación 0–100 que refleja la frecuencia transaccional de un usuario. Calculado como el logaritmo natural del conteo de transacciones, normalizado al máximo del portafolio.  
**Fórmula:** `LN(1 + COUNT(transacciones)) / MAX(LN(1 + COUNT(transacciones))) * 100`  
**Tabla:** `produccion.usuarios.score_actividad`  
**Interpretación:** 0 = sin actividad, 100 = usuario más frecuente del portafolio

---

### Concepto: Score de Rentabilidad
**Definición:** Puntuación 0–100 que refleja el volumen monetario histórico de un usuario sobre el total de usuarios activos.  
**Fórmula:** `SUM(monto) / MAX(SUM(monto) en todos los usuarios) * 100`  
**Tabla:** `produccion.usuarios.score_rentabilidad`  
**Interpretación:** 0 = sin valor monetario, 100 = usuario de mayor volumen

---

## DOMINIO: COMERCIOS

---

### Concepto: Comercio Activo
**Definición:** Comercio con `status_operacional = 'activo'` que ha procesado al menos una transacción exitosa en los últimos 30 días.  
**Sinónimos:** Merchant activo, comercio operando, afiliado en uso  
**Conceptos relacionados:** Funnel de comercios, onboarding, tasa de retención de comercios  
**Fórmula:** `merchants.ultima_actividad >= CURRENT_DATE - 30 AND status_operacional = 'activo'`  
**Tabla:** `produccion.merchants`  
**Métricas relacionadas:** Número de comercios activos, GMV por comercio

---

### Concepto: Comercio Estratégico
**Definición:** Comercio que pertenece simultáneamente al segmento de volumen "Grande" o "Mega" y al segmento de rentabilidad "Gold", "Platinum" o "Diamond". Son los comercios que generan mayor impacto en el negocio.  
**Sinónimos:** Key account, comercio ancla, merchant VIP  
**Conceptos relacionados:** Segmentación de comercios, matriz estratégica, account management  
**Umbral:** `segmento_volumen IN ('grande', 'mega') AND segmento_rentabilidad IN ('gold', 'platinum', 'diamond')`  
**Tabla:** `produccion.segmentacion_merchants`  
**Acción recomendada:** Asignación de Account Manager dedicado, SLA premium

---

### Concepto: Comercio Rentable
**Definición:** Comercio cuya tasa de MDR efectivo es igual o superior al MDR estándar (1.8%) y cuya tasa de rechazo es inferior al promedio del portafolio (< 5%).  
**Sinónimos:** Comercio de alta rentabilidad, merchant eficiente  
**Conceptos relacionados:** MDR, tasa de rechazo, margen por comercio  
**Tabla:** `produccion.segmentacion_merchants`, `produccion.mv_metricas_diarias`  
**Métricas relacionadas:** MDR por comercio, tasa de rechazo, margen neto

---

### Concepto: Comercio de Riesgo
**Definición:** Comercio con `estado_riesgo IN ('alerta', 'suspendido')` o con `tasa_rechazo_promedio > 10%` o con alertas de fraude activas y no resueltas.  
**Sinónimos:** Merchant en alerta, comercio monitoreado, afiliado en riesgo  
**Conceptos relacionados:** Fraude, score de riesgo, suspensión, tasa de rechazo  
**Tabla:** `produccion.segmentacion_merchants`, `produccion.fraude`  
**Acción recomendada:** Revisión por equipo de riesgo, posible suspensión temporal

---

### Concepto: MDR (Merchant Discount Rate)
**Definición:** Tasa de descuento que PayNova cobra al comercio sobre cada transacción aprobada. Es el principal ingreso de la empresa.  
**Sinónimos:** Tasa de descuento, comisión transaccional, tasa de intercambio  
**Valor estándar:** 1.8% del monto de la transacción  
**Fórmula en BD:** `transacciones.ingreso_comision = transacciones.monto * 0.018`  
**Tabla:** `transacciones.transacciones.ingreso_comision`  
**Conceptos relacionados:** GMV, margen, costo operativo

---

### Concepto: Onboarding de Comercio
**Definición:** Proceso estructurado de 6 etapas que un comercio atraviesa desde la firma del contrato hasta la primera transacción exitosa en producción.  
**Sinónimos:** Incorporación, alta de comercio, proceso de afiliación  
**Etapas:** Firma → KYB → Configuración técnica → Integración notificaciones → Pruebas → Activación  
**SLA estándar:** 5 días hábiles  
**Tabla:** `produccion.integraciones_merchant`  
**Métricas relacionadas:** Tiempo de activación, tasa de conversión del funnel

---

## DOMINIO: FINANZAS

---

### Concepto: GMV (Gross Merchandise Volume)
**Definición:** Suma total del monto bruto de todas las transacciones procesadas en un período, independientemente de si generaron ingreso neto positivo o negativo. Es el indicador principal de volumen del negocio.  
**Sinónimos:** TPV (Total Payment Volume), Volumen bruto, Volumen transaccionado  
**Fórmula:** `SUM(monto) WHERE estado = 'completada'`  
**Tabla:** `transacciones.transacciones`  
**Granularidad típica:** Diaria, mensual, anual  
**Distinción importante:** GMV incluye el monto total pagado por el usuario, del cual el comercio recibe el monto neto (menos MDR)

---

### Concepto: Ingresos
**Definición:** Monto total de comisiones MDR generadas por las transacciones procesadas en un período.  
**Sinónimos:** Revenue, MDR total, comisiones totales  
**Fórmula:** `SUM(ingreso_comision) WHERE estado = 'completada'`  
**Valor típico:** ~1.8% del GMV  
**Tabla:** `transacciones.transacciones`

---

### Concepto: Costos Operativos
**Definición:** Suma total de los costos de procesamiento incurridos por transacción, incluyendo fees de red, procesamiento y gestión operativa.  
**Sinónimos:** COGS transaccional, costo de procesamiento, costos variables  
**Fórmula:** `SUM(costo_operativo) WHERE estado = 'completada'`  
**Valor típico:** ~0.8% del GMV  
**Tabla:** `transacciones.transacciones`

---

### Concepto: Margen Bruto por Transacción
**Definición:** Diferencia entre el MDR cobrado y el costo operativo por transacción. Refleja la rentabilidad directa de cada operación.  
**Sinónimos:** Margen transaccional, margen neto por operación  
**Fórmula:** `ingreso_comision - costo_operativo` (columna GENERATED en BD)  
**Valor típico:** ~1.0% del monto (1.8% MDR − 0.8% costo)  
**Tabla:** `transacciones.transacciones.margen`

---

### Concepto: Ticket Promedio
**Definición:** Monto promedio de las transacciones completadas en un período. Indicador de la capacidad de gasto de los usuarios y el tipo de comercios.  
**Sinónimos:** AOV (Average Order Value), valor promedio de transacción, monto medio  
**Fórmula:** `AVG(monto) WHERE estado = 'completada'`  
**Tabla:** `transacciones.transacciones`

---

### Concepto: ROI de Campaña
**Definición:** Relación entre el ingreso incremental generado por una campaña de marketing y el costo total de la campaña (incentivos + costos de comunicación).  
**Sinónimos:** Retorno de inversión, rentabilidad de campaña  
**Fórmula:** `(Ingresos Incrementales - Costo Campaña) / Costo Campaña * 100`  
**Tabla:** `produccion.campanas`, `produccion.pagos`, `transacciones.transacciones`

---

## DOMINIO: MARKETING

---

### Concepto: Conversión
**Definición:** Acción de un usuario que cumple el objetivo definido en una campaña (primera transacción, reactivación, uso de nuevo canal, etc.) dentro de la ventana de atribución de 72 horas.  
**Sinónimos:** Conversion, acción objetivo, evento de activación  
**Conceptos relacionados:** Atribución, incrementalidad, canibalización  
**Tabla:** `produccion.campanas`, `transacciones.transacciones`

---

### Concepto: Adquisición
**Definición:** Proceso de incorporar nuevos usuarios o comercios a la plataforma PayNova. En usuarios: registro + primera transacción. En comercios: firma + onboarding completo.  
**Sinónimos:** Captación, alta nueva, incorporación  
**Métricas relacionadas:** CAC (Customer Acquisition Cost), número de nuevos usuarios/comercios  
**Tabla:** `produccion.usuarios` (fecha_registro), `produccion.merchants` (fecha_afiliacion)

---

### Concepto: Retención
**Definición:** Capacidad de mantener a un usuario o comercio activo y transaccionando a lo largo del tiempo. Se mide comparando la actividad del período actual contra el período anterior.  
**Sinónimos:** Fidelización, retención, mantenimiento de base  
**Fórmula:** `Usuarios activos en T que también estuvieron activos en T-1 / Usuarios activos en T-1`  
**Tabla:** `transacciones.transacciones`  
**Métricas relacionadas:** Tasa de retención, churn rate

---

### Concepto: Reactivación
**Definición:** Evento en que un usuario clasificado como inactivo (≥ 90 días sin transacciones) realiza una nueva transacción, volviendo al estado activo.  
**Sinónimos:** Win-back, recuperación, re-engagement  
**Umbral:** Primera transacción después de ≥ 90 días de inactividad  
**Tabla:** `transacciones.transacciones` (detección por diferencia entre fechas de transacción)  
**Métricas relacionadas:** Tasa de reactivación, costo de reactivación (CAC de win-back)

---

### Concepto: Incrementalidad
**Definición:** Medida del impacto real adicional generado por una campaña de marketing, descontando las conversiones que habrían ocurrido de forma orgánica sin la campaña.  
**Sinónimos:** Lift incremental, efecto marginal, causalidad de campaña  
**Fórmula:** `Conversiones grupo tratado - Conversiones grupo control`  
**Nota:** Requiere diseño experimental (A/B test o grupo de control) para medirse correctamente  
**Tabla:** `produccion.campanas`, `transacciones.transacciones`

---

### Concepto: Canibalización
**Definición:** Efecto negativo donde una campaña incentiva transacciones que el usuario habría realizado de todos modos, sin la intervención de marketing, reduciendo el ROI real de la acción.  
**Sinónimos:** Autocanibalization, subsidio innecesario, captura de demanda existente  
**Indicador:** ROI de campaña bajo a pesar de alta tasa de conversión  
**Tabla:** `produccion.campanas`, `transacciones.transacciones`

---

### Concepto: CAC (Customer Acquisition Cost)
**Definición:** Costo total de adquisición de un nuevo cliente o comercio, incluyendo costos de marketing, incentivos, onboarding y soporte.  
**Fórmula:** `Gasto total en adquisición del período / Nuevos usuarios/comercios adquiridos`  
**Tabla:** `produccion.pagos`, `produccion.campanas`, `produccion.notificaciones`

---

### Concepto: Open Rate
**Definición:** Porcentaje de emails entregados que fueron abiertos por el destinatario.  
**Sinónimos:** Tasa de apertura, open rate, CTR de apertura  
**Fórmula:** `Emails abiertos / Emails entregados * 100`  
**Tabla:** `produccion.notificaciones.tasa_apertura`  
**Benchmark PayNova:** > 25%

---

### Concepto: Click Rate
**Definición:** Porcentaje de emails abiertos donde el usuario hizo clic en al menos un enlace.  
**Sinónimos:** CTR, tasa de click, click-through rate  
**Fórmula:** `Clics / Emails abiertos * 100`  
**Tabla:** `produccion.notificaciones.tasa_click`  
**Benchmark PayNova:** > 8%

---

## DOMINIO: RIESGO Y FRAUDE

---

### Concepto: Fraude
**Definición:** Transacción realizada sin el conocimiento o consentimiento del titular de la tarjeta, o mediante el uso de identidades o credenciales robadas.  
**Sinónimos:** Transacción fraudulenta, fraud, estafa electrónica  
**Indicador en BD:** `fraude.flag_fraude = TRUE`  
**Tabla:** `produccion.fraude`, `transacciones.transacciones`  
**Métricas relacionadas:** Tasa de fraude, monto fraudulento, casos confirmados

---

### Concepto: Score de Riesgo
**Definición:** Probabilidad de que una transacción sea fraudulenta, calculada por el modelo de detección de fraude en tiempo real. Escala de 0 a 1.  
**Sinónimos:** Risk score, fraud score, probabilidad de fraude  
**Fuente IBM:** `[Is Fraud?] = Yes → 0.95`, `[Is Fraud?] = No → 0.05`  
**Tabla:** `transacciones.transacciones.riesgo_score`  
**Umbrales de acción:** < 0.3 verde / 0.3–0.7 monitoreo / > 0.7 alerta / > 0.9 bloqueo automático

---

### Concepto: Falso Positivo
**Definición:** Transacción legítima que fue incorrectamente clasificada como fraudulenta por el modelo de detección, resultando en un rechazo o bloqueo injustificado.  
**Sinónimos:** False positive, error tipo I, rechazo incorrecto  
**Impacto:** Pérdida de ingresos, mala experiencia del usuario, daño a la relación con el comercio  
**Tabla:** `produccion.fraude` donde `estado_revision = 'descartado'`  
**Métricas relacionadas:** Tasa de falsos positivos, precisión del modelo

---

### Concepto: Chargeback
**Definición:** Disputa iniciada por el usuario ante su banco emisor para revertir una transacción, generalmente por fraude o insatisfacción con el servicio. Resulta en un reverso de la transacción y puede implicar penalidades para el comercio.  
**Sinónimos:** Contracargo, disputa, reverso por disputa  
**Tabla:** `transacciones.transacciones` donde `estado = 'revertida'`  
**Impacto:** Pérdida del MDR cobrado + posible penalidad

---

### Concepto: Nivel de Riesgo del Usuario
**Definición:** Clasificación del perfil de riesgo de un usuario basada en el porcentaje histórico de sus transacciones marcadas como fraudulentas.  
**Fórmula de clasificación:**
- `bajo`: pct_fraude < 1%
- `medio`: pct_fraude entre 1% y 5%
- `alto`: pct_fraude entre 5% y 15%
- `critico`: pct_fraude ≥ 15%  
**Tabla:** `produccion.usuarios.nivel_riesgo`

---

## DOMINIO: OPERACIONES

---

### Concepto: Liquidación
**Definición:** Proceso de transferencia de fondos desde PayNova hacia la cuenta bancaria del comercio, correspondiente al monto neto acumulado de sus transacciones en un período.  
**Sinónimos:** Payout, desembolso, settlement, liquidación periódica  
**Tabla:** `produccion.payouts`  
**Componentes:** GMV acumulado − MDR retenido − Comisión de payout = Monto neto

---

### Concepto: SLA (Service Level Agreement)
**Definición:** Acuerdo de nivel de servicio que define los tiempos máximos comprometidos para procesos clave de la plataforma.  
**Sinónimos:** Acuerdo de servicio, tiempo de respuesta comprometido  
**SLAs principales de PayNova:**
- Autorización de transacción: < 3 segundos
- Activación de comercio estándar: 5 días hábiles
- Activación de comercio premium: 48 horas
- Procesamiento de payout: T+1 día hábil
- Resolución de alerta de fraude crítica: 1 hora

---

### Concepto: Tasa de Aprobación
**Definición:** Porcentaje de transacciones intentadas que fueron aprobadas exitosamente (estado = completada) sobre el total de intentos.  
**Sinónimos:** Approval rate, tasa de éxito transaccional  
**Fórmula:** `COUNT(completadas) / COUNT(total_intentos) * 100`  
**Tabla:** `transacciones.transacciones`  
**Meta PayNova:** ≥ 97%  
**Complemento:** Tasa de Rechazo = 100% − Tasa de Aprobación

---

### Concepto: Funnel de Comercios
**Definición:** Representación secuencial de las etapas que atraviesa un comercio desde su registro hasta estar completamente activo en todas las dimensiones operativas de la plataforma.  
**Etapas:**
1. Registrados
2. Integrados (API activa)
3. Activos (última tx ≤ 30d)
4. Con Notificaciones (email o SMS activo)
5. Con Transacciones (al menos 1 tx completada)
6. Con Payouts (al menos 1 payout procesado)  
**Tabla:** `produccion.vw_funnel_comercios`  
**Uso:** Identificar cuellos de botella en el proceso de onboarding y activación

---

### Concepto: Vista Materializada
**Definición:** En el contexto de la BD PayNova, se refiere a `mv_metricas_diarias`: una tabla pre-calculada con KPIs diarios por comercio que se refresca nocturnamente para optimizar el rendimiento del dashboard.  
**Tabla:** `produccion.mv_metricas_diarias`  
**Uso:** Fuente primaria para queries de dashboard y reportes de rendimiento de comercios

---

### Concepto: Year Month
**Definición:** Campo derivado en la tabla de transacciones con formato `YYYY-MM` que facilita la agrupación y filtrado mensual eficiente sin necesidad de extraer la fecha completa.  
**Sinónimos:** Período mensual, mes-año, período de referencia  
**Tabla:** `transacciones.transacciones.year_month`  
**Uso en SQL:** `WHERE year_month = '2019-01'` es más eficiente que `WHERE DATE_TRUNC('month', fecha_transaccion) = '2019-01-01'`
