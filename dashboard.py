"""
Barómetro 2026 — Dashboard General (Streamlit)
Conectado en vivo al Google Sheet. Ejecutar:
    streamlit run dashboard.py
"""
import io
import json
import os
import urllib.request
import urllib.parse
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

SHEET_ID = "1NklFw-P3Aa344KC3iXDRtWKdQCC_zKQRkCVWVqGzzLA"

C_TITULO = "#3D008C"
C_ACENTO = "#8A42FE"
C_OVALO = "#0F034E"
C_VERDE = "#2CA148"
C_OLIVA = "#ABAF1A"
C_NARANJA = "#F2A509"
C_ROJO = "#D94A3D"

ESCALA = {
    "Siempre": 5, "Casi siempre": 4, "Frecuentemente": 4,
    "A veces": 3, "Rara vez": 2, "Casi Nunca": 2, "Casi nunca": 2, "Nunca": 1,
}

DIM_RANGES = [
    ("Liderazgo y dirección", "30%", 0, 5),
    ("Gestión desempeño y desarrollo", "25%", 5, 9),
    ("Funcionamiento del equipo", "20%", 9, 14),
    ("Clima y seguridad psicológica", "20%", 14, 17),
    ("Recursos", "5%", 17, 20),
]

PREGUNTAS_FULL = [
    "Mi líder toma decisiones considerando la seguridad de las personas y de la información.",
    "Tengo claridad sobre lo que se espera de mí en términos de resultados y prioridades.",
    "Mi líder me brinda autonomía para tomar decisiones dentro de mi rol.",
    "Mi líder se comunica de forma clara, transparente y respetuosa, incluso en situaciones difíciles.",
    "Mi líder facilita la superación de obstáculos para lograr resultados.",
    "Mi líder me entrega feedback específico, oportuno y accionable.",
    "Mi líder me ayuda a identificar desafíos y trabajar en mi desarrollo profesional (no solo exige resultados)",
    "Mi líder me reconoce cuando hago un buen trabajo.",
    "Mi líder fomenta probar nuevas ideas y trata los errores como oportunidades de aprendizaje.",
    "El equipo logra cumplir los objetivos en los plazos definidos.",
    "En el equipo, las decisiones consideran el impacto en el cliente.",
    "Existe colaboración efectiva dentro del equipo y con otras áreas.",
    "El equipo mejora continuamente la forma en que trabaja.",
    "Si dependiera de mí, elegiría seguir siendo parte de este equipo.",
    "Puedo expresar errores, dudas o desacuerdos sin temor a consecuencias negativas.",
    "El líder promueve un ambiente de respeto e inclusión.",
    "Disfruto trabajar con mi equipo, incluso en momentos desafiantes.",
    "Cuento con los recursos necesarios para hacer mi trabajo.",
    "El equipo cuenta con las capacidades necesarias para lograr sus objetivos.",
    "En este equipo, la división de tareas y proyectos es justa y transparente.",
]

COL_MANTENER = "¿Qué prácticas del líder o del equipo deberían mantenerse porque generan buenos resultados?"
COL_CAMBIAR = "Si pudieras cambiar UNA cosa concreta en la forma de liderar o trabajar, ¿cuál sería?"
COL_ADICIONAL = "Si tienes algún comentario adicional que quieras compartir, déjalo aquí."

COMENTARIOS_JSON = os.path.join(os.path.dirname(__file__), "data", "comentarios_clasificados.json")


def gsheet_csv(sheet_name):
    url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
           f"?tqx=out:csv&sheet={urllib.parse.quote(sheet_name)}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    return pd.read_csv(io.BytesIO(raw))


@st.cache_data(ttl=300)
def load_avance():
    df = gsheet_csv("Avance")
    df = df[df["Líder"].notna() & (df["Líder"] != "TOTAL GENERAL")].copy()
    num_cols = ["Dotación", "Respuestas", "% Participación",
                "Liderazgo y dirección (30%)", "Gestión del desempeño y desarrollo (25%)",
                "Funcionamiento del equipo (20%)", "Clima y seguridad psicológica (20%)",
                "Recursos (5%)", "Resultado Ponderado (%)", "E-NPS"]
    for c in num_cols:
        df[c] = pd.to_numeric(
            df[c].astype(str).str.replace(",", ".", regex=False), errors="coerce"
        )
    return df


@st.cache_data(ttl=300)
def load_respuestas():
    return gsheet_csv("Respuestas de formulario 1")


def nota_neta(series):
    vals = series.map(ESCALA)
    vals = vals.dropna()
    if len(vals) == 0:
        return 0.0
    n45 = (vals >= 4).sum()
    n12 = (vals <= 2).sum()
    return round((n45 - n12) / len(vals) * 100, 1)


def heat_color(v):
    if v >= 80:
        return C_VERDE
    elif v >= 60:
        return C_OLIVA
    return C_NARANJA


@st.cache_data
def load_comentarios_clasificados():
    """Comentarios clasificados por LLM (sentimiento + temas), precomputado.
    Ver exportar_comentarios.py — se generó delegando la clasificación a
    agentes de Claude en chunks, ya que el ciclo de encuesta está cerrado
    y los comentarios no cambian. Si se abre un nuevo ciclo, hay que
    regenerar este archivo con datos nuevos."""
    if not os.path.exists(COMENTARIOS_JSON):
        return pd.DataFrame(columns=["id", "pregunta", "lider", "servicio", "texto", "sentimiento", "temas"])
    with open(COMENTARIOS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return pd.DataFrame(data)


def top_temas(sub_df, n=12):
    contador = Counter()
    for temas in sub_df["temas"]:
        if isinstance(temas, list):
            contador.update(temas)
    return contador.most_common(n)


def columnas_preguntas_ordenadas(df_resp):
    """Columnas reales de las 20 preguntas, en orden, dentro de respuestas del formulario."""
    cols = []
    for preg in PREGUNTAS_FULL:
        candidatos = [c for c in df_resp.columns if c.startswith("Preguntas") and preg[:40] in c]
        cols.append(candidatos[0] if candidatos else None)
    return cols


def nota_neta_pooled(df_resp, cols):
    """Calcula (Nota4+Nota5-Nota1-Nota2)/Total agrupando TODAS las respuestas
    de las columnas dadas (igual metodología que la hoja de cálculo de referencia:
    no promedia por líder, pondera cada respuesta individual por igual)."""
    cols = [c for c in cols if c is not None]
    if not cols:
        return 0.0
    vals = df_resp[cols].apply(lambda s: s.map(ESCALA))
    flat = vals.to_numpy().ravel()
    flat = flat[~pd.isna(flat)]
    if len(flat) == 0:
        return 0.0
    n45 = (flat >= 4).sum()
    n12 = (flat <= 2).sum()
    return round((n45 - n12) / len(flat) * 100, 2)


def render_individual_view(lider_nombre, av, resp_lider, coment_lider):
    """Vista individual: solo el resultado de un líder, sin acceso al resto."""
    st.title(f"Barómetro 2026 — {lider_nombre.title()}")
    st.caption(f"Servicio: {av.get('Servicio', '-')}  ·  Resultado individual, solo visible para ti")

    dotacion = av.get("Dotación", "-")
    n_resp = av.get("Respuestas", "-")
    pct_part = av.get("% Participación", "-")
    resultado = av.get("Resultado Ponderado (%)", 0)
    enps = av.get("E-NPS", "-")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Dotación", dotacion)
    c2.metric("Respuestas", n_resp)
    c3.metric("% Participación", f"{pct_part}%" if pct_part != "-" else "-")
    c4.metric("Resultado Ponderado", f"{resultado}%")
    c5.metric("E-NPS", int(enps) if enps != "-" else "-")

    if isinstance(n_resp, (int, float)) and n_resp < 8:
        st.warning(f"⚠️ Tu resultado se basa en solo {int(n_resp)} respuestas — con muestras pequeñas, "
                   "una sola respuesta puede mover el resultado varios puntos. Interprétalo con cautela.")

    st.markdown("---")
    st.subheader("Resultado por dimensión")
    dim_cols = ["Liderazgo y dirección (30%)", "Gestión del desempeño y desarrollo (25%)",
                "Funcionamiento del equipo (20%)", "Clima y seguridad psicológica (20%)", "Recursos (5%)"]
    dim_vals = [av.get(c, 0) for c in dim_cols]
    fig_dim = go.Figure(go.Bar(
        x=dim_vals, y=dim_cols, orientation="h",
        marker_color=[heat_color(v) for v in dim_vals],
        text=[f"{v}%" for v in dim_vals], textposition="outside",
    ))
    fig_dim.update_layout(xaxis_range=[0, 100], height=300, margin=dict(l=10, r=10, t=10, b=10),
                           plot_bgcolor="white", paper_bgcolor="white", font=dict(color="#2A2A2A"))
    st.plotly_chart(fig_dim, use_container_width=True)

    if resp_lider.empty:
        st.info("Aún no hay respuestas individuales registradas para calcular el detalle por pregunta.")
    else:
        st.subheader("Nota Neta por pregunta")
        preg_cols = columnas_preguntas_ordenadas(resp_lider)
        notas = [nota_neta(resp_lider[c]) if c else 0.0 for c in preg_cols]
        notas_df = pd.DataFrame({"Pregunta": [f"P{i+1}" for i in range(20)], "Nota Neta": notas,
                                  "Texto": PREGUNTAS_FULL})
        fig_q = px.bar(notas_df, x="Pregunta", y="Nota Neta", color_discrete_sequence=[C_ACENTO], text="Nota Neta")
        fig_q.update_traces(texttemplate="%{text}%", textposition="outside")
        fig_q.update_layout(yaxis_range=[min(0, notas_df["Nota Neta"].min() - 10), 100],
                             height=380, plot_bgcolor="white", paper_bgcolor="white",
                             margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_q, use_container_width=True)

        top3 = notas_df.nlargest(3, "Nota Neta")
        bot3 = notas_df.nsmallest(3, "Nota Neta")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Top 3 — Mayor puntuación**")
            for _, row in top3.iterrows():
                st.markdown(f"🟢 **{row['Pregunta']}** ({row['Nota Neta']}%) — {row['Texto']}")
        with col_b:
            st.markdown("**Bottom 3 — Menor puntuación**")
            for _, row in bot3.iterrows():
                st.markdown(f"🟠 **{row['Pregunta']}** ({row['Nota Neta']}%) — {row['Texto']}")

    st.markdown("---")
    st.subheader("Comentarios de tu equipo")
    if coment_lider is None or coment_lider.empty:
        st.info("No hay comentarios registrados.")
    else:
        preguntas_abiertas = [("¿Qué prácticas deberían mantenerse?", "mantener"),
                               ("¿Qué cambiarías?", "cambiar"), ("Comentario adicional", "adicional")]
        tabs = st.tabs([t[0] for t in preguntas_abiertas])
        iconos = {"Positivo": "🟢", "Neutro": "⚪", "Negativo": "🔴", "Sin contenido": "⚫"}
        for tab, (_, key) in zip(tabs, preguntas_abiertas):
            with tab:
                sub = coment_lider[coment_lider["pregunta"] == key]
                if sub.empty:
                    st.info("Sin comentarios en esta pregunta.")
                    continue
                for _, row in sub.iterrows():
                    icono = iconos.get(row["sentimiento"], "⚪")
                    st.markdown(f"{icono} {row['texto']}")

    st.markdown("---")
    st.caption("Este link es personal — no lo compartas. Si crees que algún dato está mal, contacta a Recursos Humanos.")


def render_heatmap_table(df_tabla, col_resultado):
    """Tabla HTML propia (evita el bug de pandas Styler + st.dataframe)."""
    rows_html = []
    for _, row in df_tabla.iterrows():
        color = heat_color(row[col_resultado])
        cells = []
        for col in df_tabla.columns:
            val = row[col]
            if col == col_resultado:
                cells.append(
                    f'<td style="background:{color};color:white;font-weight:700;'
                    f'text-align:center;padding:6px 10px;">{val:.1f}%</td>'
                )
            elif col == "% Participación":
                cells.append(f'<td style="text-align:center;padding:6px 10px;">{val:.1f}%</td>')
            elif col == "E-NPS":
                cells.append(f'<td style="text-align:center;padding:6px 10px;">{int(val)}</td>')
            elif col == "Respuestas":
                cells.append(f'<td style="text-align:center;padding:6px 10px;">{int(val)}</td>')
            else:
                cells.append(f'<td style="padding:6px 10px;">{val}</td>')
        rows_html.append(f"<tr>{''.join(cells)}</tr>")

    header_html = "".join(
        f'<th style="background:#E0E0E0;color:#404040;padding:8px 10px;'
        f'text-align:{"center" if c != df_tabla.columns[0] else "left"};">{c}</th>'
        for c in df_tabla.columns
    )
    html = f"""
    <div style="max-height:600px;overflow-y:auto;border:1px solid #ddd;border-radius:6px;">
    <table style="width:100%;border-collapse:collapse;font-size:14px;font-family:sans-serif;">
        <thead style="position:sticky;top:0;"><tr>{header_html}</tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
    </table>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


st.set_page_config(page_title="Barómetro 2026 | AMX LATAM", layout="wide", page_icon="📊")


def check_password():
    """Gate simple por contraseña usando st.secrets (configurar en Streamlit
    Cloud: Settings > Secrets -> DASHBOARD_PASSWORD = "...")."""
    try:
        expected = st.secrets.get("DASHBOARD_PASSWORD")
    except Exception:
        expected = None
    if not expected:
        return True  # sin secreto configurado (ej. desarrollo local) -> acceso libre

    def on_submit():
        st.session_state["auth_ok"] = st.session_state.get("pwd_input", "") == expected

    if st.session_state.get("auth_ok"):
        return True

    st.title("🔒 Barómetro 2026 | AMX LATAM")
    st.text_input("Contraseña de acceso", type="password", key="pwd_input", on_change=on_submit)
    if "auth_ok" in st.session_state and not st.session_state["auth_ok"]:
        st.error("Contraseña incorrecta.")
    return False


st.markdown(f"""
<style>
    .stApp {{ background-color: #F2F2F2; }}
    h1, h2, h3 {{ color: {C_TITULO} !important; }}
    [data-testid="stMetricValue"] {{ color: white !important; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{ color: white !important; }}
    div[data-testid="stMetric"] {{
        background-color: {C_OVALO};
        border-radius: 20px;
        padding: 16px 10px;
        text-align: center;
        border: 1px solid #A7A7A7;
    }}
</style>
""", unsafe_allow_html=True)

TOKENS_JSON = os.path.join(os.path.dirname(__file__), "data", "tokens.json")


def load_tokens():
    if not os.path.exists(TOKENS_JSON):
        return {}
    with open(TOKENS_JSON, encoding="utf-8") as f:
        return json.load(f)


# ── Modo individual: si la URL trae ?t=TOKEN, mostramos solo el resultado de ese líder ──
token = st.query_params.get("t")
if token:
    tokens_map = load_tokens()
    lider_token = tokens_map.get(token)
    if not lider_token:
        st.error("🔒 Link no válido o vencido. Verifica el enlace o pide uno nuevo a Recursos Humanos.")
        st.stop()

    with st.spinner("Cargando tu resultado..."):
        avance_all = load_avance()
        respuestas_all = load_respuestas()
        comentarios_all = load_comentarios_clasificados()

    fila = avance_all[avance_all["Líder"].str.strip().str.upper() == lider_token.strip().upper()]
    if fila.empty:
        st.error("No se encontró tu resultado en la hoja de cálculo. Contacta a Recursos Humanos.")
        st.stop()
    av = fila.iloc[0]

    resp_lider = respuestas_all[
        respuestas_all["Elige tu líder"].str.strip().str.upper() == lider_token.strip().upper()
    ]
    coment_lider = comentarios_all[
        comentarios_all["lider"].str.strip().str.upper() == lider_token.strip().upper()
    ] if not comentarios_all.empty else comentarios_all

    render_individual_view(lider_token, av, resp_lider, coment_lider)
    st.stop()

# ── Modo administrador: panel general con contraseña ──
if not check_password():
    st.stop()

with st.spinner("Cargando datos del Barómetro..."):
    avance = load_avance()
    respuestas = load_respuestas()

st.title("Barómetro 2026 | AMX LATAM")
st.caption("Resultados Generales — conectado en vivo al formulario")

# ── Filtros ──
with st.sidebar:
    st.header("Filtros")
    servicios = sorted(avance["Servicio"].dropna().unique())
    servicio_sel = st.multiselect("Servicio", servicios, default=[])
    coordinadores = sorted(avance["Coordinador"].dropna().unique())
    coord_sel = st.multiselect("Coordinador", coordinadores, default=[])
    lideres_opts = sorted(avance["Líder"].dropna().unique())
    lider_sel = st.multiselect("Líder", lideres_opts, default=[])
    st.divider()
    if st.button("🔄 Recargar datos"):
        st.cache_data.clear()
        st.rerun()

df = avance.copy()
if servicio_sel:
    df = df[df["Servicio"].isin(servicio_sel)]
if coord_sel:
    df = df[df["Coordinador"].isin(coord_sel)]
if lider_sel:
    df = df[df["Líder"].isin(lider_sel)]

if df.empty:
    st.warning("No hay líderes que coincidan con los filtros seleccionados.")
    st.stop()

lideres_filtrados = set(df["Líder"].str.strip().str.upper())
resp_df = respuestas[respuestas["Elige tu líder"].str.strip().str.upper().isin(lideres_filtrados)]

preg_cols_ordenadas = columnas_preguntas_ordenadas(resp_df)


# ── KPIs principales ──
tot_dot = int(df["Dotación"].sum())
tot_resp = int(df["Respuestas"].sum())
pct_part = round(tot_resp / tot_dot * 100, 2) if tot_dot else 0

dim_cols_labels = ["Liderazgo y dirección (30%)", "Gestión del desempeño y desarrollo (25%)",
                    "Funcionamiento del equipo (20%)", "Clima y seguridad psicológica (20%)", "Recursos (5%)"]
dim_pesos = [0.30, 0.25, 0.20, 0.20, 0.05]
dim_avgs = [nota_neta_pooled(resp_df, preg_cols_ordenadas[a:b]) for (_, _, a, b) in DIM_RANGES]
avg_resultado = round(sum(v * p for v, p in zip(dim_avgs, dim_pesos)), 2)
avg_enps = round(df["E-NPS"].mean(), 1)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Dotación", tot_dot)
c2.metric("Respuestas", tot_resp)
c3.metric("% Participación", f"{pct_part}%")
c4.metric("Resultado Ponderado", f"{avg_resultado}%")
c5.metric("E-NPS", int(avg_enps))
st.caption("Resultado Ponderado y por dimensión: calculado sobre el total de respuestas individuales "
           "(misma metodología que la hoja de referencia), no como promedio simple entre líderes.")

st.markdown("---")

# ── Resultado por dimensión ──
st.subheader("Resultado Ponderado por Dimensión")
dim_cols = dim_cols_labels
fig_dim = go.Figure(go.Bar(
    x=dim_avgs, y=dim_cols, orientation="h",
    marker_color=[heat_color(v) for v in dim_avgs],
    text=[f"{v}%" for v in dim_avgs], textposition="outside",
))
fig_dim.update_layout(
    xaxis_range=[0, 100], height=320, margin=dict(l=10, r=10, t=10, b=10),
    plot_bgcolor="white", paper_bgcolor="white", font=dict(color="#2A2A2A"),
)
st.plotly_chart(fig_dim, use_container_width=True)

col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Nota Neta por Pregunta")
    notas = []
    for i, preg in enumerate(PREGUNTAS_FULL):
        col_name = [c for c in resp_df.columns if c.startswith("Preguntas") and preg[:40] in c]
        col_name = col_name[0] if col_name else resp_df.columns[4 + i]
        nn = nota_neta(resp_df[col_name])
        notas.append({"Pregunta": f"P{i+1}", "Nota Neta": nn, "Texto": preg})
    notas_df = pd.DataFrame(notas)
    fig_q = px.bar(notas_df, x="Pregunta", y="Nota Neta", color_discrete_sequence=[C_ACENTO],
                    text="Nota Neta")
    fig_q.update_traces(texttemplate="%{text}%", textposition="outside")
    fig_q.update_layout(yaxis_range=[min(0, notas_df["Nota Neta"].min() - 10), 100],
                         height=380, plot_bgcolor="white", paper_bgcolor="white",
                         margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_q, use_container_width=True)

with col_b:
    st.subheader("Top y Bottom Preguntas")
    top3 = notas_df.nlargest(3, "Nota Neta")
    bot3 = notas_df.nsmallest(3, "Nota Neta")
    st.markdown("**Top 3 — Mayor puntuación**")
    for _, row in top3.iterrows():
        st.markdown(f"🟢 **{row['Pregunta']}** ({row['Nota Neta']}%) — {row['Texto']}")
    st.markdown("**Bottom 3 — Menor puntuación**")
    for _, row in bot3.iterrows():
        st.markdown(f"🟠 **{row['Pregunta']}** ({row['Nota Neta']}%) — {row['Texto']}")

st.markdown("---")

# ── Comparativa por líder (tabla HTML con semáforo) ──
st.subheader("Comparativa por Líder")
tabla = df[["Líder", "Servicio", "Coordinador", "Respuestas",
            "% Participación", "Resultado Ponderado (%)", "E-NPS"]].sort_values(
    "Resultado Ponderado (%)", ascending=False).reset_index(drop=True)
render_heatmap_table(tabla, "Resultado Ponderado (%)")

st.markdown("---")

# ── Ranking / distribución ──
col_c, col_d = st.columns(2)
with col_c:
    st.subheader("Ranking por Servicio")
    by_servicio = df.groupby("Servicio")["Resultado Ponderado (%)"].mean().sort_values(ascending=False).reset_index()
    fig_serv = px.bar(by_servicio, x="Resultado Ponderado (%)", y="Servicio", orientation="h",
                       color="Resultado Ponderado (%)",
                       color_continuous_scale=[C_NARANJA, C_OLIVA, C_VERDE], range_color=[0, 100])
    fig_serv.update_layout(height=400, plot_bgcolor="white", paper_bgcolor="white",
                            margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_serv, use_container_width=True)

with col_d:
    st.subheader("Distribución E-NPS")
    fig_enps = px.histogram(df, x="E-NPS", nbins=20, color_discrete_sequence=[C_ACENTO])
    fig_enps.update_layout(height=400, plot_bgcolor="white", paper_bgcolor="white",
                            margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_enps, use_container_width=True)

st.markdown("---")

# ── Comentarios: sentimiento y palabras frecuentes ──
st.subheader("Comentarios abiertos — sentimiento y temas frecuentes")
st.caption("Clasificación por LLM (Claude), no por conteo de palabras: cada comentario fue leído en "
           "contexto (pregunta + tono) y etiquetado con sentimiento y temas concretos. "
           "Análisis fijo del ciclo cerrado — no se recalcula en vivo.")

coment_df = load_comentarios_clasificados()
if coment_df.empty:
    st.info("Aún no se generó el análisis de comentarios. Corre exportar_comentarios.py y clasifica con un agente.")
else:
    coment_df = coment_df[coment_df["lider"].str.strip().str.upper().isin(lideres_filtrados)]

    preguntas_abiertas = [
        ("¿Qué prácticas deberían mantenerse?", "mantener"),
        ("¿Qué cambiarías?", "cambiar"),
        ("Comentario adicional", "adicional"),
    ]
    colores_map = {"Positivo": C_VERDE, "Neutro": C_OLIVA, "Negativo": C_ROJO, "Sin contenido": "#CCCCCC"}
    iconos = {"Positivo": "🟢", "Neutro": "⚪", "Negativo": "🔴", "Sin contenido": "⚫"}

    tabs = st.tabs([t[0] for t in preguntas_abiertas])
    for tab, (titulo, key) in zip(tabs, preguntas_abiertas):
        with tab:
            sub = coment_df[coment_df["pregunta"] == key]
            con_contenido = sub[sub["sentimiento"] != "Sin contenido"]
            if sub.empty:
                st.info("No hay comentarios para este filtro.")
                continue

            conteo = sub["sentimiento"].value_counts()

            col1, col2 = st.columns([1, 1.4])
            with col1:
                fig_sent = px.pie(
                    names=conteo.index, values=conteo.values,
                    color=conteo.index, color_discrete_map=colores_map, hole=0.45,
                )
                fig_sent.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                        legend=dict(orientation="h", y=-0.1))
                st.plotly_chart(fig_sent, use_container_width=True)
                c_m1, c_m2 = st.columns(2)
                c_m1.metric("Total de comentarios", len(sub))
                pct_pos = round(100 * (sub["sentimiento"] == "Positivo").sum() / max(len(con_contenido), 1), 1)
                c_m2.metric("% Positivo (con contenido)", f"{pct_pos}%")

            with col2:
                temas = top_temas(sub, n=12)
                if temas:
                    tem_df = pd.DataFrame(temas, columns=["Tema", "Frecuencia"])
                    fig_temas = px.bar(tem_df.sort_values("Frecuencia"), x="Frecuencia", y="Tema",
                                        orientation="h", color_discrete_sequence=[C_TITULO])
                    fig_temas.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                                             plot_bgcolor="white", paper_bgcolor="white")
                    st.plotly_chart(fig_temas, use_container_width=True)

            filtro_sent = st.multiselect(
                "Filtrar por sentimiento", ["Positivo", "Neutro", "Negativo", "Sin contenido"],
                default=["Positivo", "Neutro", "Negativo"], key=f"filtro_{key}"
            )
            mostrar = sub[sub["sentimiento"].isin(filtro_sent)] if filtro_sent else sub
            with st.expander(f"Ver {len(mostrar)} comentarios"):
                for _, row in mostrar.iterrows():
                    icono = iconos.get(row["sentimiento"], "⚪")
                    temas_txt = f" · _{', '.join(row['temas'])}_" if row["temas"] else ""
                    st.markdown(f"{icono} **{row['lider']}**: {row['texto']}{temas_txt}")

st.markdown("---")
st.caption(f"Datos en vivo desde Google Sheets · {len(df)} líderes · {tot_resp} respuestas")
