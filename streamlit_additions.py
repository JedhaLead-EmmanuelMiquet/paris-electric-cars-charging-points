import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# Chargement des données
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def charger_projections():
    """Charge les projections par arrondissement × scenario × horizon."""
    path = os.path.join(BASE_DIR, "energie_by_arrdt.csv")
    if not os.path.exists(path):
        path = os.path.join(BASE_DIR, "data", "energie_by_arrdt.csv")
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


@st.cache_data(ttl=3600)
def charger_scenarios_paris():
    """Charge l'agrégat Paris × 3 scenarios × 5 horizons."""
    path = os.path.join(BASE_DIR, "soutenabilite_scenarios.csv")
    if not os.path.exists(path):
        path = os.path.join(BASE_DIR, "data", "soutenabilite_scenarios.csv")
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


def _niveau_stress(pression):
    """Classe un arrondissement selon sa pression projetée."""
    if pression < 15:
        return "VERT"
    if pression < 35:
        return "AMBRE"
    return "ROUGE"


# ─────────────────────────────────────────────────────────────────────────────
# ===== BLOC 1 · Projection scénario × horizon ================================
# Ajoute un onglet qui répond à la question centrale du projet :
# « Dans N années, avec tel scénario, combien de bornes manquent, et où ? »
# ─────────────────────────────────────────────────────────────────────────────

def render_tab_projection(geojson, arr_selectionnes=None):
    st.markdown("### Projection du déficit par arrondissement")
    st.markdown(
        "> Choisissez un **scénario de croissance** et un **horizon**. "
        "La carte et le classement se recalculent."
    )

    df = charger_projections()
    if df is None:
        st.info("CSV des projections non trouvé (`energie_by_arrdt.csv`).")
        return

    col_f1, col_f2, col_k1, col_k2 = st.columns([1, 1, 1, 1])
    with col_f1:
        scenario = st.selectbox(
            "Scénario",
            options=["bas", "central", "haut"],
            index=1,
            format_func=lambda x: {
                "bas": "Bas (+20 %/an)",
                "central": "Central (+40 %/an)",
                "haut": "Haut (+60 %/an)",
            }[x],
        )
    with col_f2:
        horizon = st.slider("Horizon (années)", 1, 5, 3)

    sub = df[(df["scenario"] == scenario) & (df["horizon_years"] == horizon)].copy()
    
    if arr_selectionnes:
        col = "arr_num" if "arr_num" in sub.columns else "num_arrondissement" if "num_arrondissement" in sub.columns else None
        if col:
            sub = sub[sub[col].isin(arr_selectionnes)]
    sub["niveau_stress"] = sub["pression_projetee"].apply(_niveau_stress)

    with col_k1:
        st.metric("Bornes manquantes (Paris)",
                  f"{int(sub['deficit_bornes'].sum()):,}".replace(",", " "))
    with col_k2:
        critiques = (sub["niveau_stress"] == "ROUGE").sum()
        st.metric("Arrdts critiques", f"{critiques} / 20")

    col_carte, col_classement = st.columns([3, 2])

    with col_carte:
        if geojson is not None:
            fig = px.choropleth_map(
                sub,
                geojson=geojson,
                locations="arr_num",
                featureidkey="properties.c_ar",
                color="deficit_bornes",
                color_continuous_scale="RdYlGn_r",
                center={"lat": 48.8566, "lon": 2.3522},
                zoom=11,
                height=550,
                hover_data={
                    "deficit_bornes": True,
                    "pression_projetee": ":.1f",
                    "ve_projete": True,
                    "bornes_cible": True,
                    "niveau_stress": True,
                },
                labels={
                    "arr_num": "Arrondissement",
                    "deficit_bornes": "Bornes manquantes",
                    "pression_projetee": "Pression projetée (VE/borne)",
                    "ve_projete": "VE projetés",
                    "bornes_cible": "Bornes cible",
                    "niveau_stress": "Stress",
                },
            )
            fig.update_layout(
                mapbox_style="open-street-map",
                margin=dict(l=0, r=0, t=0, b=0),
            )
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("GeoJSON des arrondissements non disponible.")

    with col_classement:
        st.markdown("#### Top 10 à équiper en priorité")
        top = sub.sort_values("deficit_bornes", ascending=False).head(10).copy()
        top["arr_label"] = top["arr_num"].apply(
            lambda n: f"{int(n)}{'er' if n == 1 else 'e'} arr."
        )
        st.dataframe(
            top[["arr_label", "deficit_bornes", "ve_projete", "pression_projetee"]]
            .rename(columns={
                "arr_label": "Arrdt",
                "deficit_bornes": "Déficit",
                "ve_projete": "VE projetés",
                "pression_projetee": "Pression",
            })
            .reset_index(drop=True),
            width='stretch',
            height=420,
        )


# ─────────────────────────────────────────────────────────────────────────────
# ===== BLOC 2 · Classement global & comparaison scénarios ====================
# Onglet qui visualise les 3 scénarios sur 5 horizons en un seul graphique
# ─────────────────────────────────────────────────────────────────────────────

def render_tab_classement(arr_selectionnes=None):
    st.markdown("### Évolution du déficit selon les 3 scénarios")
    st.markdown(
        "> Combien de bornes manqueront à Paris, selon la vitesse de croissance du parc VE ?"
    )

    df = charger_scenarios_paris()
    if df is None:
        st.info("CSV scénarios non trouvé (`soutenabilite_scenarios.csv`).")
        return

    if arr_selectionnes:
        col = "arr_num" if "arr_num" in df.columns else "num_arrondissement" if "num_arrondissement" in df.columns else None
        if col:
            df = df[df[col].isin(arr_selectionnes)]

    couleurs = {
        "bas": "#2EF598",
        "central": "#FFD54F",
        "haut": "#FF6B6B",
    }
    labels = {
        "bas": "Bas (+20 %/an)",
        "central": "Central (+40 %/an)",
        "haut": "Haut (+60 %/an)",
    }

    fig = go.Figure()
    for scenario in ["bas", "central", "haut"]:
        sub = df[df["scenario"] == scenario].sort_values("horizon_years")
        fig.add_trace(go.Scatter(
            x=sub["horizon_years"],
            y=sub["deficit_total"],
            mode="lines+markers+text",
            name=labels[scenario],
            line=dict(color=couleurs[scenario], width=3.5),
            marker=dict(size=12, color=couleurs[scenario]),
            text=sub["deficit_total"].apply(
                lambda v: f"{int(v):,}".replace(",", " ")),
            textposition="top center",
            textfont=dict(size=10, color=couleurs[scenario]),
        ))

    fig.update_layout(
        xaxis_title="Horizon (années)",
        yaxis_title="Bornes manquantes — Paris total",
        xaxis=dict(tickmode="linear", tick0=1, dtick=1),
        height=500,
        legend=dict(x=0.02, y=0.98),
        margin=dict(l=20, r=20, t=20, b=40),
    )
    st.plotly_chart(fig, width='stretch')

    st.markdown("#### Détail par scénario")
    pivot = df.pivot_table(
        index="horizon_years",
        columns="scenario",
        values="deficit_total",
        aggfunc="sum",
    )[["bas", "central", "haut"]]
    pivot.columns = ["Bas", "Central", "Haut"]
    pivot.index.name = "Horizon (ans)"
    st.dataframe(pivot.round(0).astype(int), width='stretch')


# ─────────────────────────────────────────────────────────────────────────────
# ===== BLOC 3 · Soutenabilité énergie ========================================
# Onglet qui croise le déficit avec la capacité réseau par arrondissement
# ─────────────────────────────────────────────────────────────────────────────

def render_tab_energie(geojson):
    st.markdown("### Soutenabilité réseau · à horizon 3 ans")
    st.markdown(
        "> Installer c'est bien — encore faut-il que le réseau suive. "
        "**Niveau de stress** calculé à partir de la pression projetée."
    )

    df = charger_projections()
    if df is None:
        st.info("CSV des projections non trouvé (`energie_by_arrdt.csv`).")
        return

    scenarios = st.radio(
        "Scénario",
        options=["bas", "central", "haut"],
        index=1, horizontal=True,
        format_func=lambda x: {"bas": "Bas", "central": "Central", "haut": "Haut"}[x],
    )
    sub = df[(df["scenario"] == scenarios) & (df["horizon_years"] == 3)].copy()
    sub["niveau_stress"] = sub["pression_projetee"].apply(_niveau_stress)

    k1, k2, k3 = st.columns(3)
    with k1:
        rouge = (sub["niveau_stress"] == "ROUGE").sum()
        st.metric("Critique (rouge)", f"{rouge} arr.")
    with k2:
        ambre = (sub["niveau_stress"] == "AMBRE").sum()
        st.metric("Vigilance (ambre)", f"{ambre} arr.")
    with k3:
        vert = (sub["niveau_stress"] == "VERT").sum()
        st.metric("Soutenable (vert)", f"{vert} arr.")

    col_carte, col_chart = st.columns([3, 2])

    with col_carte:
        if geojson is not None:
            couleurs_stress = {"VERT": "#2EF598", "AMBRE": "#FFD54F", "ROUGE": "#FF6B6B"}
            fig = px.choropleth_map(
                sub,
                geojson=geojson,
                locations="arr_num",
                featureidkey="properties.c_ar",
                color="niveau_stress",
                color_discrete_map=couleurs_stress,
                category_orders={"niveau_stress": ["VERT", "AMBRE", "ROUGE"]},
                center={"lat": 48.8566, "lon": 2.3522},
                zoom=11,
                height=500,
                hover_data={
                    "pression_projetee": ":.1f",
                    "energie_add_mwh": ":,.0f",
                    "deficit_bornes": True,
                },
                labels={
                    "arr_num": "Arrdt",
                    "niveau_stress": "Niveau",
                    "pression_projetee": "Pression projetée",
                    "energie_add_mwh": "Énergie additionnelle (MWh)",
                    "deficit_bornes": "Déficit bornes",
                },
            )
            fig.update_layout(
                mapbox_style="open-street-map",
                margin=dict(l=0, r=0, t=0, b=0),
            )
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("GeoJSON non disponible.")

    with col_chart:
        st.markdown("#### Énergie additionnelle (MWh/an)")
        top_e = sub.sort_values("energie_add_mwh", ascending=False).head(10).copy()
        top_e["arr_label"] = top_e["arr_num"].apply(
            lambda n: f"{int(n)}{'er' if n == 1 else 'e'}")
        fig = px.bar(
            top_e,
            x="energie_add_mwh",
            y="arr_label",
            orientation="h",
            color="niveau_stress",
            color_discrete_map={"VERT": "#2EF598", "AMBRE": "#FFD54F", "ROUGE": "#FF6B6B"},
            height=400,
            labels={"energie_add_mwh": "MWh / an", "arr_label": "Arrdt"},
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, width='stretch')
