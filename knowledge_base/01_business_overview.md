# Documento 01 — Visión General del Negocio
## PayNova S.A. — Base de Conocimiento Empresarial

**Versión:** 1.0  
**Clasificación:** Interno — Uso analítico  
**Referencias cruzadas:** `02_operating_model.md`, `03_business_conceptual_model.md`, `08_executive_kpis.md`

---

## 1. Descripción de la Empresa

**PayNova S.A.** es una empresa de tecnología financiera (fintech) fundada en 2015, que opera una plataforma digital de pagos orientada a conectar usuarios finales con comercios a través de medios de pago electrónicos. La compañía actúa simultáneamente como adquirente, procesador y orquestador de pagos, ofreciendo una solución integral que abarca desde la captura de la transacción hasta la liquidación de fondos al comercio.

PayNova no emite tarjetas propias. Opera sobre las redes de tarjetas existentes (débito, crédito, prepago y virtual) y genera ingresos principalmente a través de la Tasa de Descuento al Comercio (MDR, por sus siglas en inglés: Merchant Discount Rate).

La empresa atiende a más de **2 millones de usuarios registrados**, tiene afiliados cerca de **3,000 comercios activos** en múltiples categorías de industria, y procesa anualmente más de **24 millones de transacciones** con un volumen bruto (GMV) creciente año sobre año.

---

## 2. Modelo de Negocio

PayNova opera bajo un modelo de plataforma de dos lados (*two-sided platform*):

```
┌──────────────┐         ┌─────────────────────┐         ┌──────────────┐
│   USUARIOS   │ ──────► │     PAYNOVA S.A.     │ ──────► │  COMERCIOS   │
│  (pagadores) │         │  (orquestador)       │         │ (receptores) │
└──────────────┘         └─────────────────────┘         └──────────────┘
       │                          │                               │
  Realiza pagos           Cobra MDR (1.8%)               Recibe fondos
  Usa tarjetas            Gestiona riesgo                Paga comisión
  Acumula beneficios      Envía notificaciones            Recibe payouts
```

### 2.1 Fuentes de Ingresos

| Fuente | Descripción | Porcentaje del ingreso total |
|--------|-------------|------------------------------|
| **MDR Transaccional** | 1.8% sobre el monto de cada transacción aprobada | ~85% |
| **Comisión de Liquidación** | Cobro sobre cada payout procesado a comercios | ~8% |
| **Servicios de Notificación** | Costo trasladado de SMS y email a comercios | ~4% |
| **Servicios Premium** | Reportes avanzados, integraciones API, SLA garantizado | ~3% |

### 2.2 Estructura de Costos

| Costo | Descripción | Porcentaje del costo total |
|-------|-------------|----------------------------|
| **Costo operativo transaccional** | 0.8% sobre cada transacción (red, procesamiento) | ~60% |
| **Infraestructura tecnológica** | Servidores, bases de datos, seguridad | ~20% |
| **Operaciones comerciales** | Account managers, onboarding, soporte | ~12% |
| **Comunicaciones** | Proveedores de email, SMS, push | ~8% |

**Margen bruto por transacción:** MDR (1.8%) − Costo operativo (0.8%) = **1.0% neto**

---

## 3. Principales Actores

### 3.1 Actores Internos

| Actor | Rol | Responsabilidades principales |
|-------|-----|-------------------------------|
| **CEO** | Dirección General | Estrategia, crecimiento, relaciones con inversores |
| **CFO** | Dirección Financiera | P&L, liquidez, reportes regulatorios |
| **COO** | Dirección de Operaciones | Operación transaccional, SLA, liquidaciones |
| **Director Comercial** | Adquisición de comercios | Onboarding, retención, expansión de red |
| **Director de Marketing** | Adquisición de usuarios | Campañas, retención, engagement |
| **Director de Riesgo** | Gestión de riesgo y fraude | Modelos, alertas, cumplimiento |
| **Account Manager** | Gestor de comercios | Acompañamiento, soporte, seguimiento KPI |
| **Analista de Datos** | Inteligencia de negocio | Reportes, dashboards, modelos analíticos |

### 3.2 Actores Externos

| Actor | Rol |
|-------|-----|
| **Usuario / Cardholder** | Realiza pagos mediante tarjeta |
| **Comercio / Merchant** | Acepta pagos y recibe liquidaciones |
| **Red de Tarjetas** | Procesa autorizaciones (Visa, Mastercard, etc.) |
| **Banco Emisor** | Emite la tarjeta del usuario |
| **Regulador** | Supervisa cumplimiento normativo |
| **Proveedor de Notificaciones** | Braze, Twilio (email, SMS, push) |

---

## 4. Flujo de Valor

```
1. ADQUISICIÓN
   Usuario descarga app / se registra
   Comercio firma contrato / completa onboarding
        ↓
2. ACTIVACIÓN
   Usuario realiza primera transacción
   Comercio procesa primera venta
        ↓
3. TRANSACCIÓN
   Usuario paga en comercio
   PayNova procesa y autoriza
   Comercio recibe confirmación
        ↓
4. GENERACIÓN DE INGRESOS
   PayNova retiene MDR (1.8%)
   Costo operativo (0.8%) se aplica
   Margen neto: 1.0% por transacción
        ↓
5. LIQUIDACIÓN
   PayNova acumula fondos del comercio
   Ejecuta payout periódico (menos comisión)
   Comercio recibe fondos en cuenta bancaria
        ↓
6. RETENCIÓN Y CRECIMIENTO
   Campañas de marketing a usuarios
   Notificaciones operativas y promocionales
   Análisis de comportamiento y segmentación
```

---

## 5. Procesos Principales

### 5.1 Proceso de Onboarding de Comercios

1. Prospección y firma de contrato
2. Carga de documentación legal (KYB)
3. Configuración técnica (API key, webhook)
4. Integración de canales de notificación (email, SMS)
5. Validación en entorno de pruebas
6. Activación en producción
7. Primera transacción exitosa → comercio "activo"

**SLA estándar:** 5 días hábiles desde firma de contrato hasta activación  
**SLA premium:** 48 horas

### 5.2 Proceso Transaccional

1. Usuario presenta tarjeta (chip, NFC, online, etc.)
2. Terminal / gateway envía solicitud a PayNova
3. PayNova valida datos de la transacción
4. PayNova envía autorización a la red de tarjetas
5. Red responde: aprobada / rechazada
6. PayNova registra resultado y notifica al comercio
7. Fondos retenidos hasta ciclo de liquidación

**Tiempo promedio de autorización:** < 3 segundos  
**Tasa de aprobación objetivo:** ≥ 97%

### 5.3 Proceso de Liquidación (Payout)

1. Cierre del período de liquidación (diario o semanal por segmento)
2. Cálculo del monto neto: GMV acumulado − MDR − comisión payout
3. Validación de cuenta bancaria del comercio
4. Emisión de transferencia bancaria
5. Confirmación de recepción
6. Registro en sistema (`produccion.payouts`)

**Frecuencia estándar:** Semanal  
**Frecuencia premium:** Diaria  
**SLA de procesamiento:** T+1 día hábil

### 5.4 Proceso de Gestión de Fraude

1. Monitoreo en tiempo real de cada transacción
2. Cálculo de `riesgo_score` por modelo ML
3. Si `riesgo_score > 0.7` → generación de alerta en `produccion.fraude`
4. Revisión manual por equipo de riesgo
5. Decisión: confirmar fraude / descartar alerta / escalar
6. Si confirmado → reverso de transacción y bloqueo de tarjeta/usuario
7. Reporte regulatorio si aplica

---

## 6. Organigrama Funcional

```
                    CEO
                     │
       ┌─────────────┼─────────────┐
       │             │             │
      CFO           COO     Dir. Riesgo
       │             │             │
   Finanzas    ┌─────┴─────┐   Analistas
   Tesorería   │           │   de Riesgo
               Ops      Comercial
           Transacc.       │
           Liquidac.   Account
                       Managers
                           │
                       Dir. Marketing
                           │
                       Campañas
                       Analytics
```

---

## 7. Objetivos Estratégicos

| Objetivo | Métrica clave | Meta anual |
|----------|---------------|------------|
| Crecimiento de GMV | Volumen total transaccionado | +20% YoY |
| Expansión de red de comercios | Nuevos comercios activos | +500 por año |
| Mejora de tasa de aprobación | % transacciones aprobadas | ≥ 97.5% |
| Reducción de fraude | Tasa de fraude sobre GMV | < 0.5% |
| Mejora de margen neto | % margen sobre GMV | > 1.1% |
| Retención de comercios | Churn de comercios | < 5% anual |
| Activación de usuarios | % usuarios que transaccionan en 30d | > 60% |

---

## 8. Posicionamiento de Mercado

PayNova se posiciona como una plataforma de pagos de segunda generación, con diferenciación basada en:

- **Analítica avanzada:** Dashboard ejecutivo con KPIs en tiempo real
- **Onboarding ágil:** Activación de comercios en < 48 horas (premium)
- **Notificaciones inteligentes:** Comunicaciones segmentadas multicanal
- **Gestión de riesgo proactiva:** Modelos ML de detección de fraude
- **API-first:** Integración sencilla para comercios digitales

**Segmentos de mercado atendidos:**
- Retail (Supermercados, Ropa, Electrónica)
- Gastronomía (Restaurantes, Cafeterías)
- Salud (Farmacias, Clínicas)
- Combustible (Gasolineras)
- Servicios (Hoteles, Aerolíneas, Educación)

---

## 9. Definiciones de Alto Nivel

| Término | Definición |
|---------|------------|
| **GMV** | Gross Merchandise Volume. Suma total del monto de transacciones procesadas en un período, independientemente del resultado financiero neto. |
| **MDR** | Merchant Discount Rate. Tasa que PayNova cobra al comercio sobre cada transacción aprobada. Se fija en 1.8% del monto. |
| **Payout** | Desembolso periódico que PayNova realiza al comercio por el monto neto de sus transacciones acumuladas. |
| **Merchant** | Empresa o persona que acepta pagos mediante la plataforma PayNova y recibe liquidaciones. |
| **Usuario** | Persona física que realiza pagos utilizando su tarjeta a través de la red de comercios PayNova. |
| **Transacción** | Operación financiera donde un usuario paga a un comercio a través de la plataforma PayNova. |
| **Score de Riesgo** | Puntuación de 0 a 1 asignada a cada transacción que indica la probabilidad de que sea fraudulenta. |
| **Onboarding** | Proceso de incorporación de un nuevo comercio a la plataforma, desde el contrato hasta la primera transacción activa. |
| **Account Manager** | Gestor comercial interno responsable de acompañar y desarrollar la relación con un portafolio de comercios. |
| **Segmento** | Clasificación de usuarios o comercios según criterios de volumen, rentabilidad o comportamiento. |
