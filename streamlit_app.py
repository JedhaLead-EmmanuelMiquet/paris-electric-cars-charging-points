import altair as alt
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import os
from typing import Optional
import folium
from folium.plugins import MarkerCluster, HeatMap
from streamlit_folium import st_folium
import branca.colormap as cm
import database
from streamlit_additions import (
    render_tab_projection,
    render_tab_classement,
    render_tab_energie,
)

# set_page_config DOIT être le premier appel Streamlit
st.set_page_config(
    page_title="Bornes VE Paris",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
filterable_values = True

if not os.path.exists(os.path.join(BASE_DIR, "bornes.db")):
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    script = os.path.join(BASE_DIR, "bornes_arrondissements.py")
    if os.path.exists(script):
        exec(open(script).read())


@st.cache_data(ttl=300)
def charger_donnees():
    """Charge les données depuis la base de données."""
    data = {}
    
    db_path = os.path.join(BASE_DIR, "bornes.db")
    if os.path.exists(db_path):
        from sqlalchemy import create_engine
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            data["bornes"] = pd.read_sql("SELECT * FROM bornes", engine)
        except Exception:
            data["bornes"] = None
        try:
            data["pression"] = pd.read_sql("SELECT * FROM pression", engine)
        except Exception:
            data["pression"] = None
        try:
            data["vehicules"] = pd.read_sql("SELECT * FROM vehicules_electriques", engine)
        except Exception:
            data["vehicules"] = None
        try:
            data["energie"] = pd.read_sql("SELECT * FROM energie", engine)
        except Exception:
            data["energie"] = None
        try:
            data["population"] = pd.read_sql("SELECT * FROM population", engine)
        except Exception:
            data["population"] = None

        if data.get("population") is None or data["population"].empty:
            from etl import recuperer_population
            pop = recuperer_population()
            if not pop.empty:
                from database import sauvegarder_population
                sauvegarder_population(pop)
                data["population"] = pop

        if data.get("population") is not None and not data.get("population").empty and data.get("pression") is not None and not data.get("pression").empty and data.get("energie") is not None and not data.get("energie").empty:
            data ["energie_pop_pression"] = pd.read_sql("""SELECT 
                e.num_arrondissement,
                e.conso_totale_mwh,
                e.nb_sites,
                p.pop_total,
                p.pop_majeurs_18plus,
                ROUND(e.conso_totale_mwh * 1.0 / p.pop_total, 2) AS mwh_par_habitant,
                ROUND(e.nb_sites * 1000.0 / p.pop_total, 1) AS sites_pour_1000_hab,
                pr.nb_pdc,
                pr.nb_ve,
                pr.pression
            FROM energie e
            LEFT JOIN population p ON e.num_arrondissement = p.num_arrondissement
            LEFT JOIN pression pr ON e.num_arrondissement = pr.num_arrondissement
            ORDER BY e.num_arrondissement
            """, engine)
        return data


@st.cache_data(ttl=3600)
def charger_geojson():
    """Charge le GeoJSON des arrondissements."""
    geojson_path = os.path.join(BASE_DIR, "arrondissements.geojson")
    if os.path.exists(geojson_path):
        with open(geojson_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


data = charger_donnees()
geojson = charger_geojson()

bornes = data.get("bornes")
pression = data.get("pression")
vehicules = data.get("vehicules")
energie = data.get("energie")
population = data.get("population")

if bornes is None or bornes.empty:
    st.error("Aucune donnée de bornes trouvée.")
    st.stop()

bornes["num_arrondissement"] = pd.to_numeric(bornes["num_arrondissement"], errors="coerce")
bornes = bornes.dropna(subset=["num_arrondissement"])
bornes["num_arrondissement"] = bornes["num_arrondissement"].astype(int)
bornes["puissance_nominale"] = pd.to_numeric(bornes["puissance_nominale"], errors="coerce")

bornes["statut_actuel"] = bornes["statut_actuel"].replace({
      "occupe": "Occupé (en charge)",
      "libre":  "Disponible",
      "inconnu":  "Inconnu"
  })


with st.sidebar:
    st.markdown("## ⚡ Filtres")
    
    arrondissements = sorted(bornes["num_arrondissement"].unique())
    arr_selectionnes = st.multiselect(
        "Arrondissements",
        options=arrondissements,
        default=arrondissements,
        format_func=lambda x: f"{x}{'er' if x == 1 else 'e'} arr."
    )

    if not arr_selectionnes:
        st.warning("Sélectionnez au moins un arrondissement.")

    if bornes is not None and not bornes.empty:
        df_puissance = bornes[
            bornes["num_arrondissement"].isin(arr_selectionnes)
        ]

    if pression is not None and not pression.empty:
        pression = pression[
            pression["num_arrondissement"].isin(arr_selectionnes)
        ]
        
    if population is not None and not population.empty:
        population = population[
            population["num_arrondissement"].isin(arr_selectionnes)
        ]

    if energie is not None and not energie.empty:
        energie["num_arrondissement"] = pd.to_numeric(energie["num_arrondissement"], errors="coerce")
        energie = energie.dropna(subset=["num_arrondissement"])
        energie["num_arrondissement"] = energie["num_arrondissement"].astype(int)
        energie = energie[energie["num_arrondissement"].isin(arr_selectionnes)]


    if st.button("🔄 Rafraîchir les statuts", width='stretch'):
            with st.spinner("Mise à jour des statuts en cours..."):
                from etl import recuperer_statuts_pdc_belib

                statuts = recuperer_statuts_pdc_belib(True)

                if statuts is not None and not statuts.empty:
                    statuts["snapshot_at"] = pd.to_datetime(statuts["snapshot_at"])
                    statuts = statuts.sort_values("snapshot_at").drop_duplicates(subset="id_pdc", keep="last")

                    # Mettre à jour le DataFrame en mémoire
                    mapping = dict(zip(statuts["id_pdc"].str.replace("*", "", regex=False), statuts["statut_pdc"]))
                    bornes["statut_actuel"] = bornes["id_pdc_itinerance"].map(mapping).fillna(bornes["statut_actuel"])
                    
                    # Resauvegarder en base
                    from database import sauvegarder_totalite_bornes
                    sauvegarder_totalite_bornes(bornes)
                    
                    st.cache_data.clear()
                    st.success(f"✅ {len(mapping)} statuts mis à jour !")
                else:
                    st.warning("Aucun statut récupéré")
            
            st.rerun()


# Entête et KPIs
st.markdown("# ⚡ Bornes de recharge VE — Paris")
st.markdown("*Outil de priorisation pour l'installation de nouvelles bornes de recharge à Paris*")

df_filtre = bornes[bornes["num_arrondissement"].isin(arr_selectionnes)]
nb_stations = df_filtre["id_station_itinerance"].nunique()
nb_pdc = len(df_filtre)
nb_disponibles = (df_filtre["statut_actuel"] == "Disponible").sum()
puissance_moy = df_filtre["puissance_nominale"].mean()

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Stations", nb_stations)
with k2:
    st.metric("Points de charge", nb_pdc)
with k3:
    st.metric("Disponibles", nb_disponibles)
with k4:
    st.metric("Puissance moyenne", f"{puissance_moy:.0f} kW" if pd.notna(puissance_moy) else "N/A")

tab_carte, tab_pression, tab_energie, tab_population, tab_proj, tab_top, tab_ene2 = st.tabs([
    "Répartition des bornes",
    "Pression sur les équipements",
    "Consommation électrique",
    "Données démographiques",
    "Projection déficitaire",
    "Evolution déficit",
    "Soutenabilité réseau"
])
 
 
with tab_carte:
    # Filtres spécifiques à cet onglet
    col_filtre1, col_filtre2 = st.columns(2)
    with col_filtre1:
        statuts = sorted(bornes["statut_actuel"].dropna().unique())
        statuts_selectionnes = st.multiselect(
            "Statut de disponibilité",
            options=statuts,
            default=statuts,
        )
    with col_filtre2:
        puissance_min, puissance_max = st.slider(
            "Puissance (kW)",
            min_value=0,
            max_value=int(bornes["puissance_nominale"].max() or 350),
            value=(0, int(bornes["puissance_nominale"].max() or 350)),
        )
    
    # Filtre combiné : arrondissement + statut + puissance
    df_filtre = bornes[
        (bornes["num_arrondissement"].isin(arr_selectionnes))
        & (bornes["statut_actuel"].isin(statuts_selectionnes))
        & (bornes["puissance_nominale"].between(puissance_min, puissance_max) | bornes["puissance_nominale"].isna())
    ]

    vue = st.radio(
        "Type de vue",
        ["Disponibilité", "Puissance", "Choroplèthe"],
        horizontal=True,
    )
    filterable_values = True
    
    if vue == "Disponibilité":
        couleurs_statuts = {
            "Disponible": "#119900",
            "Occupé (en charge)": "#FF0000",
            "Réservé": "#FAFA11",
            "En maintenance": "#5D4E43",
            "Inconnu": "#C8DEED",
        }
        fig = px.scatter_map(
            df_filtre, lat="latitude", lon="longitude",
            hover_name="nom_station",
            color="statut_actuel",
            color_discrete_map=couleurs_statuts,
            zoom=11, height=700,
            hover_data={
                "statut_actuel": True,
                "puissance_nominale": True,
                "num_arrondissement": True,
                "source": True,
                "latitude": False,
                "longitude": False,
            },
            labels={
                "statut_actuel": "Disponibilité",
                "puissance_nominale": "Puissance (kW)",
                "num_arrondissement": "Arrondissement",
                "source": "Source",
            },
        )
        fig.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width='stretch')
    
    elif vue == "Puissance":
        df_puissance = df_puissance.copy()
        df_puissance["niveau_charge"] = pd.cut(
            df_puissance["puissance_nominale"],
            bins=[0, 7, 22, 999],
            labels=["Lente (≤7 kW)", "Normale (7-22 kW)", "Rapide (>22 kW)"],
        )
        couleurs_puissance = {
            "Lente (≤7 kW)": "#CAEC0B",
            "Normale (7-22 kW)": "#4D8866",
            "Rapide (>22 kW)": "#0E4732",
        }
        fig = px.scatter_map(
            df_puissance, lat="latitude", lon="longitude",
            hover_name="nom_station",
            color="niveau_charge",
            color_discrete_map=couleurs_puissance,
            zoom=11, height=700,
        )
        fig.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width='stretch')
    
    elif vue == "Choroplèthe" and geojson:
        taux = df_filtre.groupby("num_arrondissement").agg(
            total=("statut_actuel", "count"),
            disponibles=("statut_actuel", lambda x: (x == "Disponible").sum()),
            occupees=("statut_actuel", lambda x: (x == "Occupé (en charge)").sum()),
        ).reset_index()
        denom = taux["disponibles"] + taux["occupees"]
        taux["taux_disponibilite"] = (taux["disponibles"] / denom.replace(0, float("nan")) * 100).round(1)
        
        fig = px.choropleth_map(
            taux, geojson=geojson,
            locations="num_arrondissement",
            featureidkey="properties.c_ar",
            color="taux_disponibilite",
            color_continuous_scale="RdYlGn",
            range_color=[0, 100],
            center={"lat": 48.8566, "lon": 2.3522},
            zoom=11, height=700,
            hover_data={"total": True, "disponibles": True, "occupees": True},
            labels={
                "taux_disponibilite": "Disponibilité (%)",
                "total": "Total PDC",
                "disponibles": "Disponibles",
                "occupees": "Occupés",
            },
        )
        fig.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width='stretch')
 
 
with tab_pression:
    if pression is not None and not pression.empty and geojson:
        df_pression = pression[pression["num_arrondissement"].isin(arr_selectionnes)].copy()
        df_pression["num_arrondissement"] = df_pression["num_arrondissement"].astype(int)
        st.markdown("### Pression par arrondissement")
        st.markdown("Pression = Nombre de véhicules électriques immatriculés / Nombre de points de charge.")
        st.markdown("Plus la pression est élevée, plus l'arrondissement est sous-équipé.")
        
        col_carte, col_classement = st.columns([3, 2])
        
        with col_carte:
            df_pression = pression.copy()
            df_pression["num_arrondissement"] = df_pression["num_arrondissement"].astype(int)
            
            fig = px.choropleth_map(
                df_pression, geojson=geojson,
                locations="num_arrondissement",
                featureidkey="properties.c_ar",
                color="pression",
                color_continuous_scale="RdYlGn_r",
                center={"lat": 48.8566, "lon": 2.3522},
                zoom=11, height=600,
                hover_data={
                    "pression": True,
                    "nb_ve": True,
                },
                labels={
                    "num_arrondissement": "Arrondissement",
                    "pression": "Pression (VE/borne)",
                    "nb_ve": "Véhicules électriques",
                },
            )
            fig.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, width='stretch')
        
        with col_classement:
            df_display = df_pression[["num_arrondissement", "nb_ve", "pression"]].copy()
            df_display.columns = ["Arrondissement", "Nombre VE", "Pression actuelle"]
            df_display = df_display.sort_values("Pression actuelle", ascending=True).reset_index(drop=True)

        st.dataframe(
            df_display.style.format({
                "Arrondissement": "{:,.0f}",
                "Nombre VE": "{:,.0f}",
                "Pression": "{:,.2f}",
            }).background_gradient(subset=["Pression actuelle"], cmap="Accent"),
            width='stretch',
            height='content',
            hide_index=True,
        )

    
    else:
        st.info("Données de pression non disponibles.")

with tab_energie:
    
    st.markdown("### Consommation électrique par arrondissement")

    if energie is None or energie.empty or geojson is None:
        st.info("Données de consommation électrique non disponibles.")
    else:
        df_nrj = database.charger_energie_population()
        if df_nrj is not None and not df_nrj.empty:
            df_nrj = df_nrj[df_nrj["num_arrondissement"].isin(arr_selectionnes)].copy()
            df_nrj["label"] = df_nrj["num_arrondissement"].apply(lambda x: f"{x}er" if x == 1 else f"{x}e")
            df_nrj = df_nrj.groupby("num_arrondissement").agg(conso_totale_mwh=("conso_totale_mwh", "sum"),nb_sites=("nb_sites", "sum")).reset_index()
        df_nrj = df_nrj.dropna(subset=["num_arrondissement"])
        df_nrj["num_arrondissement"] = df_nrj["num_arrondissement"].astype(int)

        if df_nrj.empty:
            st.info("Aucune donnée de consommation pour les arrondissements sélectionnés.")
        else:
            col_carte_energie, col_pression_energie = st.columns(2)
            with col_carte_energie:
                fig_nrj = px.choropleth_map(
                    df_nrj, geojson=geojson,
                    locations="num_arrondissement",
                    featureidkey="properties.c_ar",
                    color="conso_totale_mwh",
                    color_continuous_scale="YlOrRd",
                    center={"lat": 48.8566, "lon": 2.3522},
                    zoom=11, height=600,
                    hover_data={
                        "num_arrondissement": True,
                        "conso_totale_mwh": True,
                        "nb_sites": True,
                    },
                    labels={
                        "num_arrondissement": "Arrondissement",
                        "conso_totale_mwh": "Consommation (MWh)",
                        "nb_sites": "Nombre de sites",
                    },
                )
                fig_nrj.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig_nrj, width='stretch')
            
            with col_pression_energie:
                df_nrj = data.get("energie_pop_pression")
                if df_nrj is not None and not df_nrj.empty:
                    df_nrj = df_nrj[df_nrj["num_arrondissement"].isin(arr_selectionnes)].copy()
                    df_nrj["label"] = df_nrj["num_arrondissement"].apply(lambda x: f"{x}er" if x == 1 else f"{x}e")
                # Forcer l'agrégation si nécessaire
                    if len(df_nrj) > 20:
                        df_nrj = df_nrj.groupby("num_arrondissement").agg(
                            conso_totale_mwh=("conso_totale_mwh", "sum"),
                            nb_sites=("nb_sites", "sum"),
                            pop_total=("pop_total", "first"),
                            nb_pdc=("nb_pdc", "first"),
                            pression=("pression", "first"),
                        ).reset_index()
                        df_nrj["mwh_par_habitant"] = (df_nrj["conso_totale_mwh"] / df_nrj["pop_total"]).round(2)
                        df_nrj["label"] = df_nrj["num_arrondissement"].apply(
                            lambda x: f"{x}er" if x == 1 else f"{x}e"
                        )
        
        # Deux bar charts côte à côte
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            st.markdown("#### Consommation par arrondissement")
            df_sorted = df_nrj.sort_values("conso_totale_mwh", ascending=True)
            fig_bar = go.Figure(go.Bar(
                x=df_sorted["conso_totale_mwh"],
                y=df_sorted["label"],
                orientation="h",
                marker_color=df_sorted["conso_totale_mwh"],
                marker_colorscale="YlOrRd",
                text=df_sorted["conso_totale_mwh"].apply(lambda x: f"{x:,.0f}"),
                textposition="outside",
            ))
            fig_bar.update_layout(
                height=500,
                xaxis_title="MWh",
                margin=dict(l=0, r=60, t=10, b=0),
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        
        with col_g2:
            st.markdown("#### MWh par habitant")
            df_sorted2 = df_nrj.sort_values("mwh_par_habitant", ascending=True)
            fig_bar2 = go.Figure(go.Bar(
                x=df_sorted2["mwh_par_habitant"],
                y=df_sorted2["label"],
                orientation="h",
                marker_color=df_sorted2["mwh_par_habitant"],
                marker_colorscale="YlOrRd",
                text=df_sorted2["mwh_par_habitant"].apply(lambda x: f"{x:.2f}"),
                textposition="outside",
            ))
            fig_bar2.update_layout(
                height=500,
                xaxis_title="MWh / habitant",
                margin=dict(l=0, r=60, t=10, b=0),
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_bar2, use_container_width=True)

    
with tab_population:
    if population is None or population.empty:
        st.info("Données démographiques non disponibles.")
        from etl import lecture_s3, S3_BUCKET
        st.caption(f"S3_BUCKET configuré : `{S3_BUCKET or '(vide)'}`")
        df_debug = lecture_s3("paris_population")
        if df_debug is None:
            st.error("❌ `raw/data/paris_population.csv` introuvable sur S3")
        else:
            st.success(f"✅ Fichier trouvé sur S3 ({len(df_debug)} lignes) — problème ailleurs")
            st.dataframe(df_debug.head(3))
    else:
        df_pop = population.copy()
        df_pop["num_arrondissement"] = pd.to_numeric(df_pop["num_arrondissement"], errors="coerce")
        df_pop = df_pop.dropna(subset=["num_arrondissement"])
        df_pop["num_arrondissement"] = df_pop["num_arrondissement"].astype(int)
        df_pop = df_pop[df_pop["num_arrondissement"].isin(arr_selectionnes)]
        df_pop["label"] = df_pop["num_arrondissement"].apply(lambda x: f"{x}{'er' if x == 1 else 'e'} arr.")

        st.markdown("### Population par arrondissement (2021)")
        st.markdown(
        "> Répartition de la population totale entre **mineurs (0–17 ans)** et **majeurs (18 ans et +)** "
        "pour chaque arrondissement parisien — source INSEE 2021."
            )
        col_graph, col_carte = st.columns([3, 2])

        with col_graph:
            fig_bar = go.Figure()

            fig_bar.add_trace(go.Bar(
                name="Majeurs (18+)",
                x=df_pop["label"],
                y=df_pop["pop_majeurs_18plus"],
                marker_color="#0E4732",
                hovertemplate="<b>%{x}</b><br>Majeurs : %{y:,}<extra></extra>",
            ))

            fig_bar.add_trace(go.Bar(
                name="Mineurs (0–17)",
                x=df_pop["label"],
                y=df_pop["pop_mineurs_0_17"],
                marker_color="#4D8866",
                hovertemplate="<b>%{x}</b><br>Mineurs : %{y:,}<extra></extra>",
            ))

            fig_bar.update_layout(
                barmode="stack",
                height=450,
                xaxis_title="Arrondissement",
                yaxis_title="Population",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=10, r=10, t=40, b=10),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(gridcolor="rgba(200,200,200,0.3)"),
            )

            st.plotly_chart(fig_bar, width='stretch')

        with col_carte:
            st.markdown("#### Part des majeurs par arrondissement")

            fig_map = px.choropleth_map(
            df_pop,
            geojson=geojson,
            locations="num_arrondissement",
            featureidkey="properties.c_ar",
            color="pct_majeurs",
            color_continuous_scale="Greens",
            range_color=[75, 90],
            center={"lat": 48.8566, "lon": 2.3522},
            zoom=10,
            height=450,
            hover_data={
                "label": True,
                "pop_total": True,
                "pct_majeurs": True,
            },
            labels={
                "pct_majeurs": "% majeurs",
                "label": "Arrondissement",
                "pop_total": "Pop. totale",
            },
        )
            fig_map.update_layout(
                mapbox_style="open-street-map",
                margin=dict(l=0, r=0, t=0, b=0),
            )
            st.plotly_chart(fig_map, width='stretch')

        st.markdown("---")
        st.markdown("#### Détail par arrondissement")

        df_display = df_pop[["label", "pop_total", "pop_majeurs_18plus", "pop_mineurs_0_17", "pct_majeurs"]].copy()
        df_display.columns = ["Arrondissement", "Pop. totale", "Majeurs (18+)", "Mineurs (0–17)", "% Majeurs"]
        df_display = df_display.sort_values("Pop. totale", ascending=False).reset_index(drop=True)

        st.dataframe(
            df_display.style.format({
                "Pop. totale": "{:,.0f}",
                "Majeurs (18+)": "{:,.0f}",
                "Mineurs (0–17)": "{:,.0f}",
                "% Majeurs": "{:.1f}%",
            }).background_gradient(subset=["Pop. totale"], cmap="Greens"),
            width='stretch',
            hide_index=True,
        )

with tab_proj:
        render_tab_projection(geojson, arr_selectionnes)

with tab_top:
        render_tab_classement(arr_selectionnes)

with tab_ene2:
        
        render_tab_energie(geojson)
    


            
        
    

