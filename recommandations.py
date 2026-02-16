import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import json
import os
import database

st.set_page_config(page_title="Recommandations", page_icon="📍", layout="wide")
st.markdown("# 📍 Zones recommandées pour de nouvelles bornes")
st.markdown("> Analyse DBSCAN : identification des zones sous-couvertes croisées avec la pression VE.")

# Charger les données
bornes = pd.read_sql("SELECT * FROM bornes", database.get_engine())
pression = pd.read_sql("SELECT * FROM pression", database.get_engine())

geojson_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "arrondissements.geojson")
with open(geojson_path, "r", encoding="utf-8") as f:
    geojson = json.load(f)

# Paramètres dans la sidebar
with st.sidebar:
    st.markdown("## Paramètres DBSCAN")
    distance_max = st.slider("Distance min sans borne (m)", 200, 800, 300, step=50)
    min_bornes_cluster = st.slider("Bornes min par cluster", 2, 10, 3)

# DBSCAN
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

coords = bornes[["latitude", "longitude"]].dropna().values
coords_rad = np.radians(coords)

db = DBSCAN(eps=0.003, min_samples=min_bornes_cluster, metric="haversine")
bornes_clusters = db.fit_predict(coords_rad)

nb_clusters = len(set(bornes_clusters)) - (1 if -1 in bornes_clusters else 0)
nb_bruit = (bornes_clusters == -1).sum()

# Grille de points candidats
lat_min, lat_max = 48.815, 48.905
lon_min, lon_max = 2.22, 2.47
resolution = 0.003

lats = np.arange(lat_min, lat_max, resolution)
lons = np.arange(lon_min, lon_max, resolution)
grille = np.array([(lat, lon) for lat in lats for lon in lons])

tree = BallTree(coords_rad, metric="haversine")
distances, _ = tree.query(np.radians(grille), k=1)
distances_m = distances.flatten() * 6_371_000

candidats = pd.DataFrame({
    "latitude": grille[:, 0],
    "longitude": grille[:, 1],
    "distance_borne_m": distances_m.round(0),
})
candidats = candidats[candidats["distance_borne_m"] > distance_max]

# Trouver l'arrondissement de chaque candidat
from shapely.geometry import Point, shape

def trouver_arrondissement(lat, lon):
    point = Point(lon, lat)
    for feature in geojson["features"]:
        if shape(feature["geometry"]).contains(point):
            return feature["properties"]["c_ar"]
    return None

candidats["num_arrondissement"] = candidats.apply(
    lambda r: trouver_arrondissement(r["latitude"], r["longitude"]), axis=1
)
candidats = candidats.dropna(subset=["num_arrondissement"])
candidats["num_arrondissement"] = candidats["num_arrondissement"].astype(int)

# Croiser avec la pression
candidats = candidats.merge(
    pression[["num_arrondissement", "pression"]],
    on="num_arrondissement",
    how="left",
)
candidats["score_priorite"] = (candidats["distance_borne_m"] * candidats["pression"]).round(0)
candidats = candidats.sort_values("score_priorite", ascending=False)

# KPIs
k1, k2, k3 = st.columns(3)
with k1:
    st.metric("Clusters de bornes", nb_clusters)
with k2:
    st.metric("Bornes isolées", nb_bruit)
with k3:
    st.metric("Zones candidates", len(candidats))

# Carte
top = candidats.head(50)

fig = px.scatter_map(
    top, lat="latitude", lon="longitude",
    color="score_priorite",
    size="distance_borne_m",
    color_continuous_scale="YlOrRd",
    zoom=12, height=700,
    hover_data={
        "num_arrondissement": True,
        "distance_borne_m": True,
        "pression": True,
        "score_priorite": True,
    },
    labels={
        "distance_borne_m": "Distance borne la + proche (m)",
        "pression": "Pression VE/borne",
        "score_priorite": "Score priorité",
        "num_arrondissement": "Arrondissement",
    },
)
fig.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
st.plotly_chart(fig, use_container_width=True)

# Tableau
st.markdown("### Top 20 emplacements prioritaires")
st.dataframe(
    candidats.head(20)[["num_arrondissement", "latitude", "longitude", "distance_borne_m", "pression", "score_priorite"]]
    .rename(columns={
        "num_arrondissement": "Arrdt",
        "distance_borne_m": "Distance (m)",
        "pression": "Pression",
        "score_priorite": "Score",
    }),
    use_container_width=True,
    hide_index=True,
)