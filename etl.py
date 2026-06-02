# etl.py — Pipeline ETL : APIs publiques directes (sans Airflow ni S3)
import io
import re
import logging
from datetime import datetime, timedelta
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# URLs des APIs publiques
# ---------------------------------------------------------------------------
URL_BELIB = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/"
    "belib-points-de-recharge-pour-vehicules-electriques-disponibilite-temps-reel/"
    "exports/csv?limit=-1&use_labels=false&delimiter=%2C"
)
DATAGOUV_IRVE_SLUG = "fichier-consolide-des-bornes-de-recharge-pour-vehicules-electriques"


def _get_irve_url(keyword):
    """Récupère dynamiquement l'URL du dernier fichier IRVE depuis l'API data.gouv.fr."""
    try:
        api = f"https://www.data.gouv.fr/api/1/datasets/{DATAGOUV_IRVE_SLUG}/"
        data = requests.get(api, timeout=15).json()
        resources = data.get("resources", [])
        for r in resources:
            title = (r.get("title") or "").lower()
            if keyword in title:
                return r["url"]
        # Fallback : premier fichier CSV
        for r in resources:
            if r.get("format", "").lower() == "csv":
                return r["url"]
    except Exception as e:
        print(f"Impossible de récupérer l'URL IRVE ({keyword}) : {e}")
    return None


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def parser_arrondissement(code_insee):
    """Parse le numéro d'arrondissement depuis un code INSEE parisien."""
    if pd.isna(code_insee):
        return None
    code_str = str(code_insee).split(".")[0]
    if len(code_str) == 5 and code_str.startswith("751"):
        try:
            num = int(code_str[-2:])
            if 1 <= num <= 20:
                return num
        except ValueError:
            pass
    return None


def extraire_num_arrondissement(adresse):
    """Extrait le numéro d'arrondissement depuis une adresse (code postal 75xxx)."""
    if pd.isna(adresse):
        return None
    match = re.search(r"\b(75\d{3})\b", str(adresse))
    if match:
        cp = match.group(1)
        num = int(cp[-2:])
        if 1 <= num <= 20:
            return num
    return None


# ---------------------------------------------------------------------------
# API Belib (Paris Open Data)
# ---------------------------------------------------------------------------

def api_belib():
    """
    Récupère les données Belib depuis Paris Open Data.
    Retourne un DataFrame avec statut temps réel inclus.
    """
    print("Récupération Belib via Paris Open Data...")
    try:
        resp = requests.get(URL_BELIB, timeout=60)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), low_memory=False)
        print(f"Belib : {len(df)} lignes récupérées")
        return df
    except Exception as e:
        print(f"Erreur Belib API : {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# API IRVE (data.gouv.fr — fichier consolidé national)
# ---------------------------------------------------------------------------

def api_irve_statique():
    """Récupère le fichier consolidé IRVE statique et filtre Paris."""
    print("Récupération IRVE statique via data.gouv.fr...")
    try:
        url = _get_irve_url("statique") or _get_irve_url("")
        if not url:
            print("URL IRVE statique introuvable")
            return pd.DataFrame()
        print(f"IRVE statique URL : {url}")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        sep = ";" if resp.text[:500].count(";") > resp.text[:500].count(",") else ","
        df = pd.read_csv(io.StringIO(resp.text), sep=sep, low_memory=False, dtype={"code_insee_commune": str})
        # Filtrer uniquement Paris (75101 à 75120)
        if "code_insee_commune" in df.columns:
            df = df[df["code_insee_commune"].str.match(r"^751(0[1-9]|1[0-9]|20)$", na=False)]
        print(f"IRVE statique : {len(df)} lignes pour Paris")
        return df
    except Exception as e:
        print(f"Erreur IRVE statique : {e}")
        return pd.DataFrame()


def api_irve_dynamique():
    """Récupère le fichier IRVE dynamique (disponibilité temps réel) et filtre Paris."""
    print("Récupération IRVE dynamique via data.gouv.fr...")
    try:
        url = _get_irve_url("dynamique")
        if not url:
            print("URL IRVE dynamique introuvable — statuts non disponibles")
            return pd.DataFrame()
        print(f"IRVE dynamique URL : {url}")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        sep = ";" if resp.text[:500].count(";") > resp.text[:500].count(",") else ","
        df = pd.read_csv(io.StringIO(resp.text), sep=sep, low_memory=False)
        print(f"IRVE dynamique : {len(df)} lignes brutes")
        return df
    except Exception as e:
        print(f"Erreur IRVE dynamique : {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Harmonisation
# ---------------------------------------------------------------------------

def harmoniser_belib(df):
    """Normalise les colonnes Belib pour la fusion."""
    df = df.copy()

    # Coordonnées — Paris OD expose coordonneesxy = "lat,lon"
    if "latitude" not in df.columns or "longitude" not in df.columns:
        geo_col = next((c for c in df.columns if "coordonnees" in c.lower()), None)
        if geo_col:
            coords = df[geo_col].astype(str).str.split(",", expand=True)
            if coords.shape[1] >= 2:
                df["latitude"] = pd.to_numeric(coords[0], errors="coerce")
                df["longitude"] = pd.to_numeric(coords[1], errors="coerce")
    for old, new in [("lat", "latitude"), ("lon", "longitude")]:
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    # Numéro d'arrondissement — la colonne peut être "1", "Paris 1er", "75001", etc.
    def extraire_num(val):
        if pd.isna(val):
            return None
        s = str(val)
        # Code INSEE parisien ex: "75001"
        m = re.search(r"751(0[1-9]|1[0-9]|20)", s)
        if m:
            return int(m.group(1))
        # Numéro seul ex: "1" .. "20"
        m = re.search(r"\b([1-9]|1[0-9]|20)\b", s)
        if m:
            return int(m.group(1))
        return None

    for src in ["num_arrondissement", "arrondissement", "code_insee_commune", "adresse_station"]:
        if src in df.columns:
            candidate = df[src].apply(extraire_num)
            if candidate.notna().sum() > 0:
                df["num_arrondissement"] = candidate
                break

    df["num_arrondissement"] = pd.to_numeric(df["num_arrondissement"], errors="coerce")
    df = df.dropna(subset=["num_arrondissement"])
    df["num_arrondissement"] = df["num_arrondissement"].astype(int)
    df = df[df["num_arrondissement"].between(1, 20)]

    # Code INSEE
    df["code_insee_commune"] = df["num_arrondissement"].apply(lambda x: f"751{x:02d}")

    # Statut actuel
    if "statut_pdc" in df.columns and "statut_actuel" not in df.columns:
        df["statut_actuel"] = df["statut_pdc"]
    elif "statut_actuel" not in df.columns:
        df["statut_actuel"] = "Inconnu"

    # IDs itinérance
    if "id_pdc_itinerance" not in df.columns:
        df["id_pdc_itinerance"] = df.get("id_pdc", pd.Series(dtype=str))
    if "id_station_itinerance" not in df.columns:
        df["id_station_itinerance"] = df.get("id_station_local", pd.Series(dtype=str))

    # Colonnes manquantes avec valeur par défaut
    for col in ["nom_station", "nom_amenageur", "nom_operateur", "puissance_nominale", "date_mise_en_service"]:
        if col not in df.columns:
            df[col] = None
    if df["nom_station"].isna().all() and "adresse_station" in df.columns:
        df["nom_station"] = df["adresse_station"]

    df["source"] = "belib"

    cols = [
        "id_pdc_itinerance", "id_station_itinerance", "nom_station",
        "nom_amenageur", "nom_operateur",
        "puissance_nominale", "latitude", "longitude",
        "code_insee_commune", "date_mise_en_service", "source", "statut_actuel", "num_arrondissement",
    ]
    return df[[c for c in cols if c in df.columns]]


def harmoniser_gireve(df):
    """Normalise les colonnes IRVE/Gireve pour la fusion."""
    df = df.copy()

    df["num_arrondissement"] = df["adresse_station"].apply(extraire_num_arrondissement)
    df = df.dropna(subset=["num_arrondissement"])
    df["num_arrondissement"] = df["num_arrondissement"].astype(int)

    df["code_insee_commune"] = df["num_arrondissement"].apply(lambda x: f"751{int(x):02d}")
    df = df[df["code_insee_commune"].between("75101", "75120")]

    if "coordonneesXY" in df.columns:
        coords = df["coordonneesXY"].str.strip("[]").str.split(",", expand=True)
        df["longitude"] = pd.to_numeric(coords[0], errors="coerce")
        df["latitude"] = pd.to_numeric(coords[1], errors="coerce")

    if "statut_actuel" not in df.columns:
        df["statut_actuel"] = "Inconnu"

    df["source"] = "gireve"

    print(f"IRVE/Gireve Paris : {len(df)} lignes")
    cols = [
        "id_pdc_itinerance", "id_station_itinerance", "nom_station",
        "nom_amenageur", "nom_operateur",
        "puissance_nominale", "latitude", "longitude",
        "code_insee_commune", "date_mise_en_service", "source", "statut_actuel", "num_arrondissement",
    ]
    cols_present = [c for c in cols if c in df.columns]
    return df[cols_present]


def fusionner_sources(df_belib, df_gireve):
    """Fusionne Belib et IRVE/Gireve en retirant les doublons."""
    sources = [df for df in [df_belib, df_gireve] if df is not None and not df.empty]
    if not sources:
        print("Aucune source disponible — DataFrame vide retourné.")
        return pd.DataFrame()
    df = pd.concat(sources, ignore_index=True)
    print(f"Concaténation brute : {len(df)} lignes")
    if "source" in df.columns:
        df = df.sort_values("source", ascending=True)
    if "id_pdc_itinerance" in df.columns:
        df = df.drop_duplicates(subset="id_pdc_itinerance", keep="first")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Fonctions principales appelées par bornes_arrondissements.py
# ---------------------------------------------------------------------------

def recuperer_liste_stations_belib():
    """Récupère la liste des stations Belib avec statut temps réel."""
    print("Récupération des données Belib'.")
    df = api_belib()
    if df.empty:
        return None

    # Sauvegarder brut
    df.to_csv("./data/belib_paris.csv", index=False, encoding="utf-8-sig")

    df = harmoniser_belib(df)
    print(f"Belib après harmonisation : {len(df)} lignes")
    return df


def recuperer_statuts_pdc_belib(force=False):
    """
    Retourne les statuts Belib frais depuis l'API.
    Toujours appel direct à l'API (pas de cache Airflow).
    """
    df = api_belib()
    if df.empty:
        return None

    # Construire un DataFrame au format attendu par streamlit_app.py :
    # colonnes : id_pdc, statut_pdc, snapshot_at
    col_id = next((c for c in ["id_pdc_itinerance", "id_pdc_local"] if c in df.columns), None)
    col_statut = next((c for c in ["statut_pdc", "statut_actuel"] if c in df.columns), None)

    if col_id is None or col_statut is None:
        return None

    statuts = df[[col_id, col_statut]].copy()
    statuts = statuts.rename(columns={col_id: "id_pdc", col_statut: "statut_pdc"})
    statuts["snapshot_at"] = datetime.now().isoformat()
    return statuts


def recuperer_liste_stations_gireve():
    """Récupère la liste des stations IRVE/Gireve pour Paris."""
    print("Récupération des données IRVE / Gireve.")

    df_stat = api_irve_statique()
    if df_stat.empty:
        print("Aucune donnée IRVE statique disponible.")
        return pd.DataFrame()

    # Statuts dynamiques
    df_dyn = api_irve_dynamique()
    if not df_dyn.empty and "id_pdc_itinerance" in df_dyn.columns:
        # Garder la dernière ligne par PDC
        horodatage_col = next((c for c in ["horodatage", "snapshot_at"] if c in df_dyn.columns), None)
        occupation_col = next((c for c in ["occupation_pdc", "etat_pdc", "statut_pdc"] if c in df_dyn.columns), None)
        if horodatage_col and occupation_col:
            df_dyn[horodatage_col] = pd.to_datetime(df_dyn[horodatage_col], errors="coerce")
            df_dyn = (df_dyn.sort_values(horodatage_col)
                      .drop_duplicates(subset="id_pdc_itinerance", keep="last")
                      [["id_pdc_itinerance", occupation_col]])
            df_stat = df_stat.merge(df_dyn, on="id_pdc_itinerance", how="left")
            df_stat["statut_actuel"] = df_stat[occupation_col].fillna("Inconnu")
            df_stat = df_stat.drop(columns=[occupation_col], errors="ignore")
        else:
            df_stat["statut_actuel"] = "Inconnu"
    else:
        df_stat["statut_actuel"] = "Inconnu"

    df_stat = harmoniser_gireve(df_stat)
    df_stat.to_csv("./data/gireve_paris.csv", index=False)
    return df_stat


def recuperer_vehicules_electriques():
    """Récupère le stock de VE par arrondissement (Agence ORE)."""
    print("Récupération des véhicules électriques.")
    url = (
        "https://opendata.agenceore.fr/api/explore/v2.1/catalog/datasets/"
        "voitures-par-commune-par-energie/exports/csv"
        "?use_labels=false&delimiter=%3B"
    )
    df = pd.read_csv(url, sep=";", low_memory=False)
    df["codgeo"] = df["codgeo"].astype(str)
    df = df[df["codgeo"].str.match(r"^751(0[1-9]|1[0-9]|20)$")]
    df["num_arrondissement"] = df["codgeo"].str[-2:].astype(int)
    print(f"Agence ORE : {len(df)} lignes pour Paris")
    df.to_csv("./data/vehicules_electriques_paris_ORE.csv", index=False, encoding="utf-8-sig")
    return df


def recuperer_population():
    """
    Récupère la population des arrondissements parisiens.
    Source : recensement INSEE 2021 via data.gouv.fr.
    """
    print("Récupération de la population (INSEE).")
    # Fichier base-cc-evol-struct-pop depuis data.gouv.fr (communes, dont Paris arr.)
    url = "https://www.data.gouv.fr/fr/datasets/r/d9c6df9c-afce-4893-b746-b30ac15f9de8"
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        sep = ";" if resp.text[:500].count(";") > resp.text[:500].count(",") else ","
        df = pd.read_csv(io.StringIO(resp.text), sep=sep, low_memory=False, dtype={"CODGEO": str})
        df = df.dropna(subset=["CODGEO"])
        df = df[df["CODGEO"].str.match(r"^751(0[1-9]|1[0-9]|20)$", na=False)]
        df["num_arrondissement"] = df["CODGEO"].astype(str).str[-2:].astype(int)

        # Colonnes population selon le millésime INSEE
        # Chercher les colonnes pop totale et par tranche d'âge
        col_pop = next((c for c in df.columns if re.match(r"^P\d{2}_POP$", c)), None)
        col_pop0017 = next((c for c in df.columns if re.match(r"^P\d{2}_POP0014$|^P\d{2}_POP1529$", c)), None)

        if col_pop:
            df = df.rename(columns={col_pop: "pop_total"})
        elif "pop_total" not in df.columns:
            # Fallback : somme de toutes les colonnes pop numériques
            pop_cols = [c for c in df.columns if c.startswith("P") and "POP" in c and df[c].dtype in ["float64", "int64"]]
            if pop_cols:
                df["pop_total"] = df[pop_cols[0]]

        # Estimer majeurs/mineurs si colonnes présentes
        if "pop_total" in df.columns:
            # Chercher tranche 0-17 : P21_POP0014 + P21_POP1517 ou approx
            mineurs_cols = [c for c in df.columns if re.search(r"POP(00|01|02|03|04|05|06|07|08|09|10|11|12|13|14|1[5-9])(?!\d)", c)]
            if mineurs_cols:
                df["pop_mineurs_0_17"] = df[mineurs_cols].sum(axis=1)
                df["pop_majeurs_18plus"] = df["pop_total"] - df["pop_mineurs_0_17"]
            else:
                df["pop_majeurs_18plus"] = (df["pop_total"] * 0.82).round(0).astype(int)
                df["pop_mineurs_0_17"] = df["pop_total"] - df["pop_majeurs_18plus"]

        df["pct_majeurs"] = (df["pop_majeurs_18plus"] / df["pop_total"] * 100).round(1)
        df = df[df["num_arrondissement"].between(1, 20)]
        print(f"Population : {len(df)} arrondissements")
        return df

    except Exception as e:
        print(f"Erreur récupération population : {e} — utilisation données statiques INSEE 2021")
        return _population_statique_insee2021()


def _population_statique_insee2021():
    """Données population Paris 2021 (INSEE) — fallback si l'API est indisponible."""
    data = [
        (1,  17900,  14780,  3120),
        (2,  22600,  18640,  3960),
        (3,  34700,  28430,  6270),
        (4,  30400,  24930,  5470),
        (5,  60200,  49040,  11160),
        (6,  44100,  36160,  7940),
        (7,  57900,  47590,  10310),
        (8,  37300,  30580,  6720),
        (9,  61600,  50350,  11250),
        (10, 94800,  77210,  17590),
        (11, 155900, 126230, 29670),
        (12, 144200, 117600, 26600),
        (13, 183900, 148200, 35700),
        (14, 138000, 112140, 25860),
        (15, 239600, 194520, 45080),
        (16, 170200, 138860, 31340),
        (17, 170200, 138380, 31820),
        (18, 200800, 161840, 38960),
        (19, 188000, 149440, 38560),
        (20, 195500, 157760, 37740),
    ]
    df = pd.DataFrame(data, columns=["num_arrondissement", "pop_total", "pop_majeurs_18plus", "pop_mineurs_0_17"])
    df["CODGEO"] = df["num_arrondissement"].apply(lambda x: f"751{x:02d}")
    df["pct_majeurs"] = (df["pop_majeurs_18plus"] / df["pop_total"] * 100).round(1)
    print(f"Population statique INSEE 2021 : {len(df)} arrondissements")
    return df


def enedis_paris_data(annee):
    """Récupère les données de consommation Enedis pour Paris."""
    base_url = (
        "https://opendata.enedis.fr/data-fair/api/v1/datasets/"
        "consommation-electrique-par-secteur-dactivite-iris/lines"
    )
    all_data = []
    page = 1
    size = 993

    while True:
        try:
            resp = requests.get(base_url, params={
                "qs": f"code_departement:75 AND annee:{annee}",
                "size": size,
                "select": "code_iris,code_commune,nom_commune,code_grand_secteur,conso_totale_mwh,nb_sites",
                "page": page,
            }, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            all_data.extend(results)
            if len(all_data) >= data.get("total", 0):
                break
            page += 1
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                print(f"Enedis pagination terminée page {page}")
                break
            raise

    df = pd.DataFrame(all_data)
    if "code_iris" in df.columns:
        df["num_arrondissement"] = df["code_iris"].astype(str).str[:5].apply(parser_arrondissement)
    elif "code_commune" in df.columns:
        df["num_arrondissement"] = df["code_commune"].apply(parser_arrondissement)
    print(f"Enedis {annee} : {len(df)} lignes Paris, arrondissements : {df['num_arrondissement'].dropna().unique().tolist()}")
    df.to_csv("./data/energie_paris.csv", index=False, encoding="utf-8-sig")
    return df


def calculer_projections(pression):
    if pression is None or pression.empty:
        return pd.DataFrame(), pd.DataFrame()
    scenarios = {"bas": 0.20, "central": 0.40, "haut": 0.60}
    PRESSION_CIBLE = 10
    lignes_arrdt, lignes_paris = [], []
    for scenario, taux in scenarios.items():
        for horizon in range(1, 6):
            total_deficit = 0
            for _, row in pression.iterrows():
                arr = int(row["num_arrondissement"])
                nb_ve = row.get("nb_ve", 0) or 0
                nb_pdc = row.get("nb_pdc", 0) or 0
                ve_proj = int(nb_ve * (1 + taux) ** horizon)
                bornes_cible = max(int(ve_proj / PRESSION_CIBLE), nb_pdc)
                deficit = max(0, bornes_cible - nb_pdc)
                pression_proj = round(ve_proj / nb_pdc, 1) if nb_pdc > 0 else 999
                lignes_arrdt.append({
                    "arr_num": arr, "scenario": scenario, "horizon_years": horizon,
                    "ve_projete": ve_proj, "bornes_cible": bornes_cible,
                    "deficit_bornes": deficit, "pression_projetee": pression_proj,
                    "energie_add_mwh": round(deficit * 2.5, 1),
                })
                total_deficit += deficit
            lignes_paris.append({
                "scenario": scenario, "horizon_years": horizon,
                "deficit_total": total_deficit,
            })
    return pd.DataFrame(lignes_arrdt), pd.DataFrame(lignes_paris)
