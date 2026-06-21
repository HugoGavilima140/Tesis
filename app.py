"""
app.py — Interfaz Streamlit del Business Reasoning Agent de PayNova.

Ejecutar:
    streamlit run app.py

Desde el directorio raíz del proyecto (wikisql_agentic_rag/).
"""

import sys
import time
import traceback
from pathlib import Path
from typing import Optional

import streamlit as st

# ─── Path setup ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

# ─── Configuración de página ──────────────────────────────────────────────────
st.set_page_config(
    page_title="PayNova · Business AI Agent",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Estilos CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Fondo del chat más limpio */
.stChatMessage { border-radius: 12px; margin-bottom: 8px; }

/* Tarjeta de confianza */
.confidence-card {
    background: linear-gradient(135deg, #1e3a5f, #2d6a9f);
    color: white;
    border-radius: 10px;
    padding: 12px 18px;
    margin: 8px 0;
    font-size: 14px;
}

/* Badges de dominio */
.domain-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    margin: 2px;
}
.badge-finanzas   { background:#dbeafe; color:#1e40af; }
.badge-marketing  { background:#fce7f3; color:#9d174d; }
.badge-operaciones{ background:#dcfce7; color:#166534; }
.badge-riesgo     { background:#fee2e2; color:#991b1b; }
.badge-ejecutivo  { background:#f3e8ff; color:#6b21a8; }
.badge-estrategia { background:#fef9c3; color:#854d0e; }
.badge-general    { background:#f1f5f9; color:#475569; }

/* Highlight de hallazgos */
.finding-box {
    border-left: 4px solid #3b82f6;
    padding: 8px 14px;
    margin: 4px 0;
    background: #f0f7ff;
    border-radius: 0 8px 8px 0;
    font-size: 14px;
}

/* Barra de confianza */
.conf-bar-container { margin: 6px 0; }

/* Mensaje de estado */
.status-thinking {
    color: #6b7280;
    font-style: italic;
    font-size: 13px;
}

/* Header */
.main-header {
    background: linear-gradient(135deg, #0f172a, #1e3a5f);
    color: white;
    padding: 20px 24px;
    border-radius: 12px;
    margin-bottom: 16px;
}
</style>
""", unsafe_allow_html=True)


# ─── Inicialización del agente (cacheado) ────────────────────────────────────

@st.cache_resource(show_spinner=False)
def load_agent(force_rebuild_kb: bool = False):
    """Carga el BusinessReasoningAgent una sola vez por sesión."""
    from agente.pipeline.react_loop import BusinessReasoningAgent
    return BusinessReasoningAgent(force_rebuild_kb=force_rebuild_kb)


def get_agent():
    """Retorna el agente (lo inicializa si es la primera vez)."""
    rebuild = st.session_state.get("rebuild_kb", False)
    return load_agent(force_rebuild_kb=rebuild)


# ─── Estado de sesión ────────────────────────────────────────────────────────

def init_session():
    if "messages" not in st.session_state:
        st.session_state.messages = []   # [{role, content, meta}]
    if "agent_ready" not in st.session_state:
        st.session_state.agent_ready = False
    if "verbose" not in st.session_state:
        st.session_state.verbose = False
    if "show_sql" not in st.session_state:
        st.session_state.show_sql = True
    if "show_trace" not in st.session_state:
        st.session_state.show_trace = False
    if "rebuild_kb" not in st.session_state:
        st.session_state.rebuild_kb = False


# ─── Helpers de UI ───────────────────────────────────────────────────────────

def domain_badge(domain: str) -> str:
    css = f"badge-{domain}" if domain in [
        "finanzas","marketing","operaciones","riesgo","ejecutivo","estrategia"
    ] else "badge-general"
    return f'<span class="domain-badge {css}">{domain.upper()}</span>'


def confidence_bar(score: int, label: str) -> str:
    color = "#22c55e" if score >= 85 else "#f59e0b" if score >= 70 else "#ef4444"
    pct   = score
    return f"""
    <div class="conf-bar-container">
        <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:13px; color:#6b7280;">Confianza</span>
            <span style="font-weight:700; color:{color};">{label}</span>
            <span style="font-size:12px; color:#9ca3af;">{score}/100</span>
        </div>
        <div style="background:#e5e7eb; border-radius:6px; height:8px; margin-top:4px;">
            <div style="background:{color}; width:{pct}%; height:8px; border-radius:6px; transition:width 0.5s;"></div>
        </div>
    </div>
    """


def render_response(response, step_results=None, trace_text: str = ""):
    """Renderiza la respuesta ejecutiva en la UI."""

    # Banner KB-directo [Mod 1]
    if getattr(response, "kb_was_sufficient", False):
        st.info("ℹ️ **Respuesta directa desde documentación empresarial** (sin consulta SQL)")

    # Resumen ejecutivo
    st.markdown(f"### {response.executive_summary}")

    # Hallazgos
    if response.findings:
        st.markdown("**Hallazgos clave:**")
        for finding in response.findings:
            st.markdown(
                f'<div class="finding-box">• {finding}</div>',
                unsafe_allow_html=True
            )

    # Evidencia
    if response.evidence and "validados" not in response.evidence:
        st.info(f"**Evidencia:** {response.evidence}")

    # Razonamiento (expandible)
    if response.reasoning:
        with st.expander("📐 Razonamiento del agente", expanded=False):
            st.markdown(response.reasoning)

    # Riesgos identificados [Mod 9]
    risks = getattr(response, "risks", [])
    if risks:
        with st.expander(f"⚠️ Riesgos identificados ({len(risks)})", expanded=True):
            for r in risks:
                st.markdown(f"- {r}")

    # Recomendaciones accionables [Mod 9]
    recommendations = getattr(response, "recommendations", [])
    if recommendations:
        with st.expander(f"✅ Recomendaciones ({len(recommendations)})", expanded=True):
            for i, rec in enumerate(recommendations, 1):
                st.markdown(f"{i}. {rec}")

    # Barra de confianza
    st.markdown(
        confidence_bar(response.confidence_score, response.confidence_label),
        unsafe_allow_html=True
    )

    # Breakdown de confianza + critic verdict [Mod 8 + Mod 6]
    confidence_components = getattr(response, "confidence_components", None)
    critic_verdict        = getattr(response, "critic_verdict", "sufficient")
    if confidence_components or critic_verdict:
        with st.expander("🔬 Detalle de confianza (Mod 8)", expanded=False):
            if confidence_components:
                labels = {
                    "retrieval": "Recuperación KB",
                    "plan": "Plan",
                    "sql": "SQL",
                    "business": "Validación negocio",
                    "critic": "Critic agent",
                    "iter_penalty": "Penalización reintentos",
                }
                cols = st.columns(3)
                for i, (key, label) in enumerate(labels.items()):
                    val = int(confidence_components.get(key, 0))
                    color = "#22c55e" if val >= 80 else "#f59e0b" if val >= 60 else "#ef4444"
                    with cols[i % 3]:
                        st.markdown(
                            f"<small style='color:#6b7280;'>{label}</small><br>"
                            f"<b style='color:{color};'>{val}</b>",
                            unsafe_allow_html=True
                        )
            if critic_verdict:
                verdict_colors = {
                    "sufficient": "✅", "replan": "🔄",
                    "retable": "📋", "retry_sql": "🔧",
                }
                icon = verdict_colors.get(critic_verdict, "")
                st.caption(f"Critic agent: {icon} `{critic_verdict}`")

    # Limitaciones
    if response.limitations:
        with st.expander("⚠️ Limitaciones y supuestos", expanded=False):
            for lim in response.limitations:
                st.markdown(f"- {lim}")

    # Aclaración requerida
    if response.requires_clarification and response.clarification_questions:
        st.warning("**Necesito más información para responder con precisión:**")
        for q in response.clarification_questions:
            st.markdown(f"- {q}")

    # Interpretaciones de ambigüedad
    if response.ambiguity_interpretations:
        st.warning(f"**Ambigüedad detectada:** {response.ambiguity_interpretations[0]}")

    # SQL ejecutado (si está habilitado)
    if st.session_state.show_sql and step_results:
        successful = [sr for sr in step_results if sr.success and sr.sql and sr.sql != ";"]
        if successful:
            with st.expander(f"🔍 SQL ejecutado ({len(successful)} consulta(s))", expanded=False):
                for sr in successful:
                    st.markdown(f"**Paso {sr.step_number}** — {sr.row_count} filas")
                    st.code(sr.sql, language="sql")
                    if sr.anomalies:
                        for anomaly in sr.anomalies:
                            st.warning(f"⚠️ {anomaly}")
                    # Muestra de datos
                    if sr.rows and sr.row_count > 0:
                        import pandas as pd
                        try:
                            df = pd.DataFrame(sr.rows[:20])
                            st.dataframe(df, use_container_width=True)
                        except Exception:
                            st.json(sr.rows[:5])

    # Trazado ReAct
    if st.session_state.show_trace and trace_text:
        with st.expander("🧠 Trazado ReAct completo", expanded=False):
            st.code(trace_text, language="text")


def render_welcome():
    """Pantalla de bienvenida cuando no hay mensajes."""
    st.markdown("""
    <div class="main-header">
        <h2 style="margin:0; font-size:22px;">🏦 PayNova Business AI Agent</h2>
        <p style="margin:6px 0 0; opacity:0.8; font-size:14px;">
            Agente analítico empresarial con razonamiento ReAct + Multi-Hop
        </p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    example_groups = [
        ("**💰 Finanzas**", col1, [
            "¿Cuál fue el GMV del mes pasado?",
            "¿Cuánto generamos en MDR este año?",
            "¿Cómo está el margen bruto transaccional?",
        ]),
        ("**🏪 Comercios**", col2, [
            "¿Qué comercios son los más rentables?",
            "¿Cómo está el funnel de onboarding?",
            "¿Cuántos comercios están activos?",
        ]),
        ("**⚠️ Riesgo y Ops**", col3, [
            "¿Cuál es la tasa de aprobación actual?",
            "¿Qué Account Manager tiene mejor portafolio?",
            "¿Cuál es la tasa de fraude por canal?",
        ]),
    ]

    btn_idx = 0
    for label, col, questions in example_groups:
        with col:
            st.markdown(label)
            for q in questions:
                if st.button(q, key=f"example_btn_{btn_idx}", use_container_width=True):
                    st.session_state.pending_question = q
                    st.rerun()
                btn_idx += 1


# ─── Sidebar ─────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/bank-building.png", width=60)
        st.title("PayNova AI Agent")
        st.caption("Business Reasoning Agent v2.0 · 9 Mods")
        st.divider()

        # Estado del agente
        st.markdown("### Estado del sistema")
        try:
            agent = get_agent()
            st.success("✅ Agente iniciado")
            kb_stats = {"chunks": len(agent.kb_retriever._chunks)}
            st.caption(f"KB: {kb_stats['chunks']} chunks indexados")
            mem_stats = agent.memory.get_stats()
            st.caption(f"Memoria: {sum(mem_stats.values())} entradas")
            st.session_state.agent_ready = True
        except Exception as e:
            st.error(f"❌ Error: {str(e)[:80]}")
            st.session_state.agent_ready = False
            with st.expander("Ver detalles del error"):
                st.code(traceback.format_exc(), language="text")

        st.divider()

        # Opciones de visualización
        st.markdown("### Opciones de análisis")
        st.session_state.show_sql = st.toggle(
            "Mostrar SQL generado", value=True,
            help="Muestra las consultas SQL ejecutadas y sus resultados"
        )
        st.session_state.show_trace = st.toggle(
            "Mostrar trazado ReAct", value=False,
            help="Muestra el ciclo Think→Act→Observe completo"
        )
        st.session_state.verbose = st.toggle(
            "Modo verbose (consola)", value=False,
            help="Imprime el progreso en la consola del servidor"
        )

        st.divider()

        # Acciones
        st.markdown("### Acciones")

        if st.button("🗑️ Limpiar conversación", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        if st.button("📊 Ver estadísticas de memoria", use_container_width=True):
            try:
                agent = get_agent()
                stats = agent.memory.get_stats()
                st.info("\n".join([f"**{k}:** {v}" for k, v in stats.items()]))
            except Exception as e:
                st.error(str(e))

        if st.button("🔄 Reconstruir índice KB", use_container_width=True):
            st.session_state.rebuild_kb = True
            st.cache_resource.clear()
            st.success("Índice limpiado. Reiniciando...")
            time.sleep(1)
            st.rerun()

        st.divider()

        # Info del sistema
        st.markdown("### Arquitectura (v2.0)")
        st.markdown("""
        ```
        Pregunta → IntentAnalyzer
               → MemoryRetrieval  [Mod 2]
               → KB Retriever
               → KB Validator     [Mod 1]
               ├── KB-directo (sin SQL)
               └── MultiHop Plan  [Mod 3]
                     → TableRetrieval
                     → TableValidator [Mod 4]
                     → SQL Reasoning
                     → Execution (PG)
                     → BizValidator  [Mod 5]
               → Reflection
               → CriticAgent      [Mod 6/7]
               → ConfidenceEst.   [Mod 8]
               → ExecFormatter    [Mod 9]
        ```
        """)

        st.caption("🎓 Tesis Maestría IA · PayNova S.A.")


# ─── Procesamiento de pregunta ───────────────────────────────────────────────

def process_question(question: str):
    """Procesa una pregunta y agrega la respuesta al historial."""

    # Agregar mensaje del usuario
    st.session_state.messages.append({
        "role": "user",
        "content": question,
        "meta": {},
    })

    # Placeholder para el streaming visual
    with st.chat_message("assistant", avatar="🤖"):
        status_container = st.empty()
        response_container = st.empty()

        # Fases del ReAct con feedback visual (refleja arquitectura v2.0)
        phases = [
            ("🧠 Analizando intención de negocio...", 0.4),
            ("🗃️ Recuperando memoria histórica [Mod 2]...", 0.3),
            ("📚 Recuperando conocimiento empresarial...", 0.4),
            ("🔎 Validando suficiencia de KB [Mod 1]...", 0.3),
            ("📋 Generando plan + subproblemas [Mod 3]...", 0.4),
            ("🔍 Seleccionando y validando tablas [Mod 4]...", 0.3),
            ("⚙️ Generando y ejecutando SQL + validación negocio [Mod 5]...", 0.3),
            ("🔎 Reflexionando — Critic agent [Mod 6/7]...", 0.4),
            ("📊 Estimando confianza compuesta [Mod 8]...", 0.3),
            ("✍️ Redactando respuesta ejecutiva 7 secciones [Mod 9]...", 0.3),
        ]

        t_start = time.time()

        try:
            agent = get_agent()

            # Mostrar fases de razonamiento (simulación visual)
            for msg, _ in phases[:-1]:
                status_container.markdown(
                    f'<p class="status-thinking">{msg}</p>',
                    unsafe_allow_html=True
                )
                time.sleep(0.3)

            # Ejecutar el agente real
            response = agent.answer(question, verbose=st.session_state.verbose)

            # Obtener step_results y trace adjuntos por el react_loop
            step_results = getattr(response, "step_results", None)
            trace_text   = getattr(response, "trace_text", "")

            status_container.empty()
            elapsed = time.time() - t_start

            # Mostrar meta-info
            response_container.empty()

            # Renderizar en el contenedor del mensaje
            render_response(response, step_results, trace_text)

            # Tiempo de respuesta
            st.caption(f"⏱️ Tiempo de análisis: {elapsed:.1f}s")

            # Guardar en historial
            st.session_state.messages.append({
                "role": "assistant",
                "content": response.to_text(),
                "meta": {
                    "confidence": response.confidence_score,
                    "confidence_label": response.confidence_label,
                    "elapsed": elapsed,
                    "step_results": step_results,
                    "kb_was_sufficient": getattr(response, "kb_was_sufficient", False),
                    "critic_verdict": getattr(response, "critic_verdict", "sufficient"),
                    "confidence_components": getattr(response, "confidence_components", None),
                    "risks": getattr(response, "risks", []),
                    "recommendations": getattr(response, "recommendations", []),
                },
            })

        except Exception as e:
            status_container.empty()
            error_msg = str(e)
            st.error(f"**Error durante el análisis:** {error_msg[:200]}")
            with st.expander("Detalle del error"):
                st.code(traceback.format_exc(), language="text")

            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Error: {error_msg}",
                "meta": {"error": True},
            })


# ─── Renderizado del historial ───────────────────────────────────────────────

def render_history():
    """Renderiza el historial de conversación."""
    for i, msg in enumerate(st.session_state.messages):
        if msg["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🤖"):
                meta = msg.get("meta", {})

                if meta.get("error"):
                    st.error(msg["content"])
                else:
                    # Re-renderizar respuesta desde el texto guardado
                    step_results = meta.get("step_results")
                    st.markdown(msg["content"])

                    # Mostrar SQL si está guardado
                    if st.session_state.show_sql and step_results:
                        successful = [sr for sr in step_results if sr.success and sr.sql]
                        if successful:
                            with st.expander(f"🔍 SQL ({len(successful)} consulta(s))", expanded=False):
                                for sr in successful:
                                    st.markdown(f"**Paso {sr.step_number}**")
                                    st.code(sr.sql, language="sql")
                                    if sr.rows:
                                        import pandas as pd
                                        try:
                                            st.dataframe(pd.DataFrame(sr.rows[:20]), use_container_width=True)
                                        except Exception:
                                            pass

                    if meta.get("elapsed"):
                        conf  = meta.get("confidence", 0)
                        label = meta.get("confidence_label", "")
                        col_c, col_t = st.columns([3, 1])
                        with col_c:
                            st.markdown(
                                confidence_bar(conf, label),
                                unsafe_allow_html=True
                            )
                        with col_t:
                            st.caption(f"⏱️ {meta['elapsed']:.1f}s")


# ─── Función principal ───────────────────────────────────────────────────────

def main():
    init_session()
    render_sidebar()

    # Header principal
    st.markdown("""
    <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
        <span style="font-size:32px;">🏦</span>
        <div>
            <h1 style="margin:0; font-size:26px; color:#0f172a;">PayNova Business AI Agent</h1>
            <p style="margin:0; color:#64748b; font-size:14px;">
                Arquitectura evolucionada: ReAct · Multi-Hop · Critic · Confidence (9 Mods)
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Si no hay agente, mostrar mensaje
    if not st.session_state.agent_ready:
        st.warning("⚙️ Configurando el agente... Revisa el sidebar para ver el estado.")

    # Mostrar bienvenida si no hay mensajes
    if not st.session_state.messages:
        render_welcome()

    # Historial de conversación
    else:
        render_history()

    # Manejar pregunta pendiente (desde botones de ejemplo)
    if "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")
        if question and st.session_state.agent_ready:
            process_question(question)
            st.rerun()

    # Input del chat
    st.divider()
    if prompt := st.chat_input(
        "Escribe tu pregunta de negocio sobre PayNova...",
        disabled=not st.session_state.agent_ready,
    ):
        process_question(prompt)
        st.rerun()


if __name__ == "__main__":
    main()
