# Documento 10 — Manual del Agente de IA
## PayNova S.A. — Guía de Razonamiento para Agentes SQL, RAG y Analíticos

**Versión:** 1.0  
**Propósito:** Manual de operación para agentes de IA. Define cómo interpretar preguntas de negocio, seleccionar tablas, navegar el modelo de datos, resolver ambigüedades y producir respuestas confiables.  
**Dirigido a:** Agentes Text-to-SQL, Agentes RAG, Copilots Ejecutivos, LLMs en modo benchmark  
**Referencias cruzadas:** Todos los documentos de la base de conocimiento (01–09)

---

## PARTE 1 — ARQUITECTURA DEL MODELO DE DATOS

### 1.1 Mapa de Navegación de Tablas

El modelo de datos de PayNova usa dos esquemas PostgreSQL:

```
ESQUEMA: produccion          ESQUEMA: transacciones
├── usuarios                 └── transacciones (TABLA PRINCIPAL)
├── tarjetas
├── merchants (CLAVE)
├── segmentacion_merchants
├── account_managers
├── integraciones_merchant
├── payouts
├── notificaciones
├── fraude
├── segmentacion
├── campanas
└── pagos
```

**Jerarquía de importancia para análisis:**
1. `transacciones.transacciones` — Tabla central. Todo análisis de volumen, ingresos, margen empieza aquí.
2. `produccion.merchants` — Maestro de comercios. Conecta todo lo relacionado con comercios.
3. `produccion.segmentacion_merchants` — Clasificación de comercios para análisis estratégico.
4. `produccion.payouts` — Para análisis de liquidaciones y eficiencia operativa.
5. `produccion.notificaciones` — Para análisis de costos de comunicación y marketing.
6. `produccion.fraude` — Para análisis de riesgo.
7. `produccion.usuarios` — Para análisis de la base de clientes.

---

### 1.2 Claves de Unión (JOINs Críticos)

| Para unir... | Tabla A | Columna A | Tabla B | Columna B |
|-------------|---------|-----------|---------|-----------|
| Transacciones con Comercios | `transacciones.transacciones` | `merchant_id` | `produccion.merchants` | `merchant_id` |
| Transacciones con Usuarios | `transacciones.transacciones` | `usuario_origen_id` | `produccion.usuarios` | `usuario_id` |
| Transacciones con Fraude | `transacciones.transacciones` | `transaccion_id` | `produccion.fraude` | `transaccion_id` |
| Comercios con Segmentación | `produccion.merchants` | `merchant_id` | `produccion.segmentacion_merchants` | `merchant_id` |
| Comercios con Account Manager | `produccion.merchants` | `coordinador_id` | `produccion.account_managers` | `manager_id` |
| Comercios con Integración | `produccion.merchants` | `merchant_id` | `produccion.integraciones_merchant` | `merchant_id` |
| Comercios con Payouts | `produccion.merchants` | `merchant_id` | `produccion.payouts` | `merchant_id` |
| Comercios con Notificaciones | `produccion.merchants` | `merchant_id` | `produccion.notificaciones` | `merchant_id` |
| Usuarios con Segmentación | `produccion.usuarios` | `usuario_id` | `produccion.segmentacion` | `usuario_id` |

---

### 1.3 Columnas Columnas Generadas (GENERATED ALWAYS AS)

Estas columnas NO necesitan cálculo manual en las queries. Ya están calculadas en la BD:

| Tabla | Columna | Fórmula implícita |
|-------|---------|-------------------|
| `transacciones.transacciones` | `ingreso_comision` | `monto * 0.018` |
| `transacciones.transacciones` | `costo_operativo` | `monto * 0.008` |
| `transacciones.transacciones` | `margen` | `ingreso_comision - costo_operativo` |
| `produccion.payouts` | `monto_neto` | `monto - comision_payout` |
| `produccion.notificaciones` | `costo_total` | `cantidad_enviada * costo_unitario` |

**Regla del agente:** Para calcular rentabilidad, **siempre usar `SUM(margen)`**, no calcular `SUM(monto) * 0.010` manualmente.

---

### 1.4 Campos de Tiempo Disponibles

| Campo | Tabla | Formato | Uso típico |
|-------|-------|---------|-----------|
| `fecha_transaccion` | `transacciones.transacciones` | TIMESTAMP | Filtros precisos de fecha/hora |
| `year_month` | `transacciones.transacciones` | VARCHAR 'YYYY-MM' | Filtros y agrupaciones mensuales (más eficiente) |
| `hora_transaccion` | `transacciones.transacciones` | INTEGER 0–23 | Análisis por hora del día |
| `dia_semana` | `transacciones.transacciones` | VARCHAR | Análisis por día de semana |
| `mes_nombre` | `transacciones.transacciones` | VARCHAR | Display en reportes |
| `fecha_registro` | `produccion.usuarios` | DATE | Análisis de cohortes de usuarios |
| `fecha_afiliacion` | `produccion.merchants` | DATE | Antigüedad del comercio |
| `fecha_payout` | `produccion.payouts` | DATE | Período de liquidación |
| `fecha_envio` | `produccion.notificaciones` | TIMESTAMP | Análisis de campañas |

**Regla del agente:** Para filtrar por mes, usar `year_month = 'YYYY-MM'` en lugar de `DATE_TRUNC('month', fecha_transaccion) = 'YYYY-MM-01'`. Es más eficiente y puede aprovechar índices.

---

## PARTE 2 — REGLAS DE INTERPRETACIÓN

### 2.1 Mapa de Preguntas → Tablas

Cuando recibas una pregunta, identifica el dominio y selecciona las tablas según esta guía:

| Pregunta sobre... | Tabla principal | Tablas auxiliares |
|------------------|----------------|-------------------|
| GMV / Volumen / Ingresos / Margen | `transacciones.transacciones` | — |
| Número de transacciones / Ticket promedio | `transacciones.transacciones` | — |
| Usuarios activos / Retención / Churn | `transacciones.transacciones` | `produccion.usuarios` |
| Comercios activos / Nuevos / Churn | `produccion.merchants` | `transacciones.transacciones` |
| Segmento de comercio (grande, micro...) | `produccion.segmentacion_merchants` | `produccion.merchants` |
| Account Manager / Coordinador | `produccion.account_managers` | `produccion.merchants` |
| Payouts / Liquidaciones | `produccion.payouts` | `produccion.merchants` |
| Notificaciones / Costo comunicaciones | `produccion.notificaciones` | `produccion.merchants` |
| Fraude / Riesgo | `produccion.fraude` | `transacciones.transacciones` |
| Funnel de comercios | `produccion.vw_funnel_comercios` | — |
| Rentabilidad por comercio (completa) | `produccion.mv_metricas_diarias` | — |
| Categoría de comercio (MCC) | `produccion.merchants` | `transacciones.transacciones` |
| Canal de transacción | `transacciones.transacciones` | — |
| Retención por cohorte | `transacciones.transacciones` | `produccion.usuarios` |

---

### 2.2 Desambiguación de Términos Críticos

El agente DEBE distinguir entre términos que suenan similares pero significan cosas diferentes:

#### "Activo" tiene múltiples significados:

| Contexto | Campo | Significado |
|----------|-------|-------------|
| `produccion.usuarios.estado = 'activo'` | Estado del ciclo de vida del usuario | El usuario NO está suspendido ni bloqueado. NO significa que haya transaccionado recientemente. |
| "Usuario activo" en métricas | Derivado de `transacciones.transacciones` | Usuario con al menos 1 tx completada en los últimos 30 días. |
| `produccion.merchants.status_operacional = 'activo'` | Estado del comercio | El comercio puede procesar transacciones. NO significa que haya procesado recientemente. |
| "Comercio activo" en métricas | `ultima_actividad >= CURRENT_DATE - 30` | Comercio que procesó transacciones en los últimos 30 días. |

**Regla del agente:** Cuando alguien pregunta por "usuarios activos" o "comercios activos", siempre interpretar como actividad transaccional reciente (30 días), NO como el campo de estado en la tabla maestra.

---

#### "Ingreso" vs. "GMV" vs. "Margen":

| Término | Columna | Qué representa |
|---------|---------|----------------|
| GMV / Volumen | `SUM(monto)` | Lo que pagó el usuario. No es ingreso de PayNova. |
| Ingreso / MDR | `SUM(ingreso_comision)` | Lo que gana PayNova (1.8% del GMV). |
| Margen | `SUM(margen)` | Lo que queda después de costos de procesamiento (1.0% del GMV). |

**Regla del agente:** Si alguien dice "ingresos de PayNova", usar `SUM(ingreso_comision)`. Si dice "volumen de ventas de los comercios", usar `SUM(monto)`.

---

#### "Monto de payout" vs. "Monto neto de payout":

| Término | Columna | Qué representa |
|---------|---------|----------------|
| Monto de payout | `produccion.payouts.monto` | El monto bruto del desembolso antes de comisión |
| Monto neto de payout | `produccion.payouts.monto_neto` | Lo que efectivamente recibe el comercio |

**Regla del agente:** Para reportar cuánto recibieron los comercios, siempre usar `monto_neto`.

---

### 2.3 Palabras Clave y su Traducción SQL

| Término natural | Traducción SQL |
|----------------|----------------|
| "último mes" / "el mes pasado" | `year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')` |
| "este mes" | `year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE), 'YYYY-MM')` |
| "último año" / "año anterior" | `year_month >= TO_CHAR(CURRENT_DATE - INTERVAL '12 months', 'YYYY-MM')` |
| "últimos 30 días" | `fecha_transaccion >= CURRENT_DATE - 30` |
| "comercios grandes" | `segmento_volumen IN ('grande', 'mega')` |
| "comercios estratégicos" | `segmento_volumen IN ('grande', 'mega') AND segmento_rentabilidad IN ('gold', 'platinum', 'diamond')` |
| "usuarios premium" | `segmento_rentabilidad = 'platinum'` |
| "transacciones exitosas" / "aprobadas" | `estado = 'completada'` |
| "transacciones rechazadas" | `estado = 'rechazada'` |
| "tasa de aprobación" | `COUNT(CASE WHEN estado = 'completada' THEN 1 END) / COUNT(*) * 100` |
| "tasa de fraude" | `COUNT(flag_fraude=TRUE) / COUNT(*) * 100` |
| "fraude confirmado" | `produccion.fraude WHERE estado_revision = 'confirmado'` |
| "payouts exitosos" | `produccion.payouts WHERE estado = 'procesado'` |
| "canal online" | `canal_pago = 'online'` |
| "canal chip" / "presencial" | `canal_pago = 'chip'` o `canal_pago = 'contactless'` |
| "supermercados" | `mcc = '5411'` o `mcc_categoria ILIKE '%supermercado%'` |
| "restaurantes" | `mcc = '5812'` o `mcc_categoria ILIKE '%restaurante%'` |

---

## PARTE 3 — PATRONES DE RAZONAMIENTO

### 3.1 Patrón: Pregunta sobre Tendencia Temporal

**Cuándo aplicar:** El usuario pregunta por "cómo ha evolucionado", "cuál es la tendencia", "mes a mes", "año a año".

**Patrón de razonamiento:**
1. Identificar la métrica (GMV, transacciones, comercios, etc.)
2. Determinar la granularidad temporal (mensual, semanal)
3. Usar `GROUP BY year_month` para transacciones o `DATE_TRUNC` para otras tablas
4. Agregar `LAG()` o `AVG() OVER` para variaciones y medias móviles
5. Incluir la comparación YoY si el período lo permite

**Template:**
```sql
SELECT year_month, [métricas], 
    [métrica] / LAG([métrica]) OVER (ORDER BY year_month) * 100 - 100 AS variacion_mom_pct
FROM transacciones.transacciones
WHERE estado = 'completada'
GROUP BY year_month
ORDER BY year_month;
```

---

### 3.2 Patrón: Pregunta sobre Top-N

**Cuándo aplicar:** "¿Cuáles son los 10 mejores?", "Top comercios", "¿Quiénes más?"

**Patrón de razonamiento:**
1. Identificar la métrica de ordenamiento (GMV, MDR, margen, transacciones)
2. Agregar la entidad de agrupación (merchant_id, usuario_id, manager_id)
3. Ordenar DESC por la métrica
4. Limitar con `LIMIT N`
5. Incluir nombre y datos de contexto para que el resultado sea legible

---

### 3.3 Patrón: Pregunta Comparativa

**Cuándo aplicar:** "Comparar", "diferencia entre", "vs.", "¿cuál es mejor?"

**Patrón de razonamiento:**
1. Crear dos CTEs: una para cada período/segmento/categoría a comparar
2. Unir con UNION ALL o JOIN
3. Calcular la diferencia y el porcentaje de variación
4. Presentar ambos valores en la misma fila para facilitar comparación

---

### 3.4 Patrón: Pregunta de Composición (% del Total)

**Cuándo aplicar:** "¿Qué porcentaje?", "¿cuánto representa?", "distribución de"

**Patrón de razonamiento:**
1. Calcular el total en una CTE o subconsulta
2. Calcular el subtotal por dimensión
3. Dividir subtotal / total * 100

**Template:**
```sql
WITH total AS (SELECT SUM([métrica]) AS total_global FROM ...),
     por_dimension AS (SELECT dimensión, SUM([métrica]) AS subtotal FROM ... GROUP BY dimensión)
SELECT dimensión, subtotal, ROUND(subtotal / total.total_global * 100, 2) AS pct_del_total
FROM por_dimension CROSS JOIN total
ORDER BY subtotal DESC;
```

---

### 3.5 Patrón: Segmentación de Cohortes

**Cuándo aplicar:** "Por cohorte de registro", "usuarios de enero", "comercios que se unieron en Q1"

**Patrón de razonamiento:**
1. Definir la fecha de inicio de la cohorte (registro de usuario o afiliación de comercio)
2. Agrupar por período de inicio (mes, trimestre)
3. Para cada cohorte, calcular las métricas en diferentes períodos de observación
4. Comparar la evolución de cada cohorte a lo largo del tiempo

---

## PARTE 4 — REGLAS ANTI-ALUCINACIÓN

### 4.1 Lo que el Agente NO debe hacer

**NUNCA inventar nombres de columnas.** Si no está en el diccionario de datos (`04_data_dictionary.md`), no existe en la BD.

**NUNCA asumir que `status = 'activo'` implica actividad transaccional reciente.** Verificar siempre con la tabla `transacciones.transacciones`.

**NUNCA usar `SUM(monto)` como proxy de ingresos de PayNova.** Los ingresos son `SUM(ingreso_comision)`.

**NUNCA confundir `monto` de payouts con `monto_neto`.** El comercio recibe `monto_neto`, no `monto`.

**NUNCA reportar la tasa de fraude del dataset IBM (~2.5%) como la tasa objetivo de PayNova.** La meta es < 0.5%. El dataset es de entrenamiento con fraude sintético elevado.

**NUNCA hacer operaciones de escritura (INSERT, UPDATE, DELETE) a partir de preguntas analíticas.** Solo SELECT.

**NUNCA asumir que dos registros con el mismo nombre son la misma entidad** sin verificar la clave primaria (`merchant_id`, `usuario_id`, etc.).

---

### 4.2 Verificaciones antes de Responder

Antes de producir una respuesta SQL, verificar:

| Verificación | Pregunta |
|-------------|----------|
| ¿Filtré por `estado = 'completada'`? | Para métricas de GMV, ingresos y margen, solo usar transacciones completadas. |
| ¿Usé la columna GENERATED en lugar de calcular manualmente? | `margen`, `ingreso_comision`, `costo_operativo`, `monto_neto` ya están calculados. |
| ¿El JOIN es correcto? | Verificar que las claves de unión coinciden con la tabla de JOINs críticos (Sección 1.2). |
| ¿El filtro de tiempo es eficiente? | Usar `year_month` en vez de `DATE_TRUNC` para transacciones. |
| ¿El resultado es razonable? | GMV mensual típico: decenas de millones. MDR típico: ~1.8% del GMV. Tasa de aprobación típica: ~97%. |
| ¿La pregunta requería JOIN con `fraude`? | Solo hacer JOIN si la pregunta involucra específicamente fraude. No agregar por defecto. |

---

### 4.3 Rangos de Validación de Resultados

Si una respuesta produce valores fuera de estos rangos, revisar la query:

| Métrica | Rango esperado (mensual) |
|---------|--------------------------|
| GMV total | $10M – $500M |
| MDR rate efectivo | 1.5% – 2.0% |
| Tasa de aprobación | 90% – 99% |
| Tasa de fraude | 0.1% – 5% |
| Ticket promedio | $10 – $500 |
| Número de transacciones/mes | 200,000 – 2,000,000 |
| Comercios activos | 1,500 – 3,000 |
| Usuarios activos (MAU) | 10,000 – 200,000 |

---

## PARTE 5 — VISTAS Y ACCESOS RÁPIDOS

### 5.1 Cuándo Usar Vistas vs. Tablas Base

| Vista / Materializada | Cuándo usarla | Ventaja |
|----------------------|---------------|---------|
| `produccion.vw_funnel_comercios` | Preguntas sobre funnel de onboarding | Cálculo pre-hecho; no requiere múltiples JOINs |
| `produccion.vw_matriz_comercios_estrategicos` | Análisis de la matriz estratégica de comercios | Segmentación cruzada pre-calculada |
| `produccion.vw_waterfall_rentabilidad` | Análisis del waterfall de rentabilidad | Descomposición de margen ya calculada |
| `produccion.vw_kpi_dashboard` | KPIs de resumen rápido | Métricas principales sin necesidad de agregaciones |
| `produccion.mv_metricas_diarias` | Rendimiento diario por comercio | Datos pre-calculados; consulta mucho más rápida que calcular desde `transacciones` |

**Regla:** Para dashboards y reportes de alto tráfico, preferir `mv_metricas_diarias` sobre calcular directamente desde `transacciones.transacciones`.

---

### 5.2 Queries Canónicas de Referencia

**KPIs del mes actual:**
```sql
SELECT
    year_month,
    COUNT(*) AS total_intentos,
    SUM(CASE WHEN estado = 'completada' THEN monto ELSE 0 END) AS gmv,
    SUM(CASE WHEN estado = 'completada' THEN ingreso_comision ELSE 0 END) AS ingresos_mdr,
    SUM(CASE WHEN estado = 'completada' THEN margen ELSE 0 END) AS margen_bruto,
    ROUND(COUNT(CASE WHEN estado = 'completada' THEN 1 END)::NUMERIC / COUNT(*) * 100, 2) AS tasa_aprobacion_pct,
    COUNT(DISTINCT CASE WHEN estado = 'completada' THEN merchant_id END) AS comercios_activos,
    COUNT(DISTINCT CASE WHEN estado = 'completada' THEN usuario_origen_id END) AS usuarios_activos
FROM transacciones.transacciones
WHERE year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE), 'YYYY-MM')
GROUP BY year_month;
```

**Top 10 comercios por GMV del último mes:**
```sql
SELECT
    m.merchant_id,
    m.merchant_name,
    sm.segmento_volumen,
    ROUND(SUM(t.monto), 2) AS gmv,
    ROUND(SUM(t.ingreso_comision), 2) AS mdr,
    COUNT(t.transaccion_id) AS transacciones
FROM transacciones.transacciones t
JOIN produccion.merchants m ON t.merchant_id = m.merchant_id
LEFT JOIN produccion.segmentacion_merchants sm ON m.merchant_id = sm.merchant_id
WHERE t.estado = 'completada'
  AND t.year_month = TO_CHAR(DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month', 'YYYY-MM')
GROUP BY m.merchant_id, m.merchant_name, sm.segmento_volumen
ORDER BY gmv DESC
LIMIT 10;
```

**Usuarios inactivos en riesgo (90–180 días sin tx):**
```sql
SELECT
    u.usuario_id,
    u.nivel_riesgo,
    s.segmento_rentabilidad,
    MAX(t.fecha_transaccion) AS ultima_transaccion,
    CURRENT_DATE - MAX(t.fecha_transaccion)::DATE AS dias_inactivo,
    COUNT(t.transaccion_id) AS tx_historicas,
    ROUND(SUM(t.monto), 2) AS gmv_historico
FROM produccion.usuarios u
JOIN transacciones.transacciones t ON u.usuario_id = t.usuario_origen_id
LEFT JOIN produccion.segmentacion s ON u.usuario_id = s.usuario_id
WHERE u.estado NOT IN ('suspendido', 'bloqueado')
  AND t.estado = 'completada'
GROUP BY u.usuario_id, u.nivel_riesgo, s.segmento_rentabilidad
HAVING (CURRENT_DATE - MAX(t.fecha_transaccion)::DATE) BETWEEN 90 AND 180
ORDER BY gmv_historico DESC;
```

---

## PARTE 6 — RESUMEN DE ÍNDICES DISPONIBLES

Los índices disponibles en la BD afectan directamente la eficiencia de las queries. Usar las columnas indexadas en cláusulas WHERE y JOIN:

| Tabla | Columnas con índice | Uso recomendado |
|-------|--------------------|-----------------| 
| `transacciones.transacciones` | `merchant_id`, `usuario_origen_id`, `fecha_transaccion`, `year_month`, `estado`, `riesgo_score`, `flag_fraude` | Filtrar siempre por `year_month` o `fecha_transaccion` + `estado` |
| `produccion.merchants` | `merchant_id` (PK), `status_operacional`, `mcc`, `coordinador_id` | Filtrar por `status_operacional` antes de JOINs |
| `produccion.payouts` | `merchant_id`, `fecha_payout`, `estado` | Filtrar por `estado = 'procesado'` para métricas |
| `produccion.notificaciones` | `merchant_id`, `fecha_envio`, `tipo_canal` | Filtrar por `tipo_canal` para análisis por canal |
| `produccion.fraude` | `transaccion_id`, `estado_revision`, `flag_fraude` | JOIN con `transaccion_id` es eficiente |

---

## PARTE 7 — GUÍA PARA RESPUESTAS EJECUTIVAS

### 7.1 Formato de Respuesta Recomendado

Para respuestas a preguntas ejecutivas, incluir siempre:

1. **Valor del período actual** — El número principal que responde la pregunta
2. **Comparación con período anterior** — Variación absoluta y porcentual
3. **Contexto de benchmark** — Si está por encima o debajo de la meta
4. **Una frase interpretativa** — Qué significa el resultado para el negocio
5. **Acción recomendada** (si corresponde) — Qué debería hacer el equipo

### 7.2 Ejemplo de Respuesta Tipo

**Pregunta:** "¿Cuál fue la tasa de aprobación del mes pasado?"

**Respuesta tipo:**
> La tasa de aprobación del mes pasado fue **96.8%**, ligeramente por debajo de la meta de 97%. Comparada con el mismo mes del año anterior (97.3%), hay una caída de 0.5 puntos porcentuales. El análisis por canal muestra que las transacciones online tienen mayor tasa de rechazo (5.2%) que las presenciales (1.8%), lo que sugiere revisar el flujo de autenticación en el canal digital.

---

## APÉNDICE — GLOSARIO RÁPIDO PARA EL AGENTE

| Abreviatura | Significado completo |
|-------------|---------------------|
| GMV | Gross Merchandise Volume — Volumen bruto de transacciones |
| MDR | Merchant Discount Rate — Tasa de descuento al comercio (1.8%) |
| MAU | Monthly Active Users — Usuarios activos mensuales |
| CAC | Customer Acquisition Cost — Costo de adquirir un nuevo cliente |
| LTV | Lifetime Value — Valor total que genera un cliente en su ciclo de vida |
| SLA | Service Level Agreement — Tiempo de respuesta comprometido |
| KYB | Know Your Business — Verificación del comercio en onboarding |
| MCC | Merchant Category Code — Código de categoría del comercio (ISO 18245) |
| RFM | Recency, Frequency, Monetary — Marco de segmentación de clientes |
| AOV | Average Order Value — Ticket promedio (= Monto promedio por transacción) |
| YoY | Year over Year — Comparación con el mismo período del año anterior |
| MoM | Month over Month — Comparación con el mes anterior |
| CTR | Click-Through Rate — Tasa de clics sobre impresiones |
| NPS | Net Promoter Score — Índice de recomendación de clientes |
| CAGR | Compound Annual Growth Rate — Tasa de crecimiento anual compuesto |
| COG | Cost of Goods — Costo operativo directo por transacción |
| P&L | Profit and Loss — Estado de resultados |
| CRM | Customer Relationship Management — Sistema de gestión de clientes |
| API | Application Programming Interface — Interfaz de integración técnica |
| KPI | Key Performance Indicator — Indicador clave de rendimiento |
