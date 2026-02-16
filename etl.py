#etl.py — Pipeline ETL : API Airflow → S3
import io
import os
import re
import sys
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import requests
import boto3

# Configuration S3
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_PREFIX = os.environ.get("S3_PREFIX", "datasets/")
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")
EMAIL = os.environ.get("ALH_EMAIL")
PASSWORD = os.environ.get("ALH_PASSWORD")

def collect_data(source, fromdate=None, todate=None, force=False):
    """Lit depuis S3, fallback sur l'API Airflow si S3 non configuré."""
    
    # Priorité 1 : S3
    if S3_BUCKET and not force:
        df = lecture_s3(source)
        if df is not None:
            return df
    
    # Fallback : API Airflow (ancien comportement)
    EMAIL = os.environ.get("ALH_EMAIL")
    PASSWORD = os.environ.get("ALH_PASSWORD")
    if EMAIL and PASSWORD:
        return lecture_airflow(source, fromdate, todate)
    
    #Cas extrême si aucun des deux ne fonctionne on renvoie une erreur
    print(f"Ni S3 ni Airflow configurés pour {source}")
    return None

def lecture_s3(source):
    """Lecture S3."""
    try:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        cle = f"raw/data/{source}.csv"
        obj = s3.get_object(Bucket=S3_BUCKET, Key=cle)
        df = pd.read_csv(io.BytesIO(obj["Body"].read()), low_memory=False)
        print(f"Récupération de [{source}] {len(df)} lignes depuis S3")
        return df
    except Exception as e:
        print(f"Attention : [{source}] S3 KO : {e}")
        return None
    

def lecture_airflow(source, fromdate=None, todate=None):
    try:
        if fromdate is None:
            maintenant = datetime.now().replace(minute=0, second=0, microsecond=0)
            if maintenant.hour > 2:
                maintenant = maintenant.replace(hour=maintenant.hour - 2)
            else:
                maintenant = (maintenant - timedelta(days=1)).replace(hour=23)    
            fromdate = (maintenant - timedelta(hours=2)).strftime("%Y-%m-%d")
        if todate is None:
            todate = maintenant.strftime("%Y-%m-%d")
        if not EMAIL or not PASSWORD:
            return None
        else:
        #récupérer les données sur le serveur AirFlow, en utilisant une requête GET avec les paramètres d'authentification et de date spécifiés, et en convertissant la réponse JSON en un DataFrame pandas pour une manipulation ultérieure.
            url = "https://alh-consulting.com/api/bornes-ve/data"
            params = {
            "source": source,
            "from": fromdate,
            "to": todate,
            }
            auth = (EMAIL, PASSWORD)  # authentification basique avec email et mot de passe

            response = requests.get(url, params=params, auth=auth, timeout=60)
            df = pd.read_csv(io.StringIO(response.text), low_memory=False, dtype={
            "code_insee_commune": str,
            "prise_type_ef": str,
            "prise_type_2": str,
            "prise_type_combo_ccs": str,
            "prise_type_chademo": str,
            "prise_type_autre": str,
            "paiement_acte": str,
            "paiement_cb": str,
            "reservation": str,
            "station_deux_roues": str,
            })
            return df
    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de l'import des données : {source} - {e}")
        return None
    

def harmoniser_gireve(df):
    """Normalise les colonnes Gireve pour la fusion avec le dataset principal."""
    df = df.copy()
    df['num_arrondissement'] = df['adresse_station'].apply(extraire_num_arrondissement)
    df["code_insee_commune"] = df['num_arrondissement'].apply(lambda x: f"751{int(x):02d}" if pd.notna(x) else None)
    df = df[df["code_insee_commune"].between("75101", "75120")]
    print(f"Nombre d'enregistrements uniques récupérés pour Gireve : {len(df)} lignes")
    if "coordonneesXY" in df.columns:
        # Parser les coordonnées "[lon, lat]" en deux colonnes
        coords = df["coordonneesXY"].str.strip("[]").str.split(",", expand=True)
        df["longitude"] = pd.to_numeric(coords[0], errors="coerce")
        df["latitude"] = pd.to_numeric(coords[1], errors="coerce")
    df["source"] = "gireve"
    
    return df[[
        "id_pdc_itinerance", "id_station_itinerance", "nom_station",
        "nom_amenageur", "nom_operateur",
        "puissance_nominale", "latitude", "longitude",
        "code_insee_commune", "date_mise_en_service", "source","statut_actuel","num_arrondissement"
    ]]

def harmoniser_belib(df):
    """Normalise les colonnes Belib pour la fusion avec le dataset principal."""
    df = df.copy()
    df = df.rename(columns={"lat": "latitude", "lon": "longitude"})
    #On va renommer latitude et longitude pour les faire correspondre à l'autre source, afin de faciliter la fusion ultérieure des deux sources de données.
    
    # Tenter de reconstruire proprement le code commune INSEE manquant depuis le numéro d'arrondissement
    df["code_insee_commune"] = df["num_arrondissement"].apply(
        lambda x: f"751{int(x):02d}" if pd.notna(x) else None
    )
    
    df["source"] = "belib"
    
    #Récupérer uniquement les colonnes nécessaires pour la fusion : 
    return df[[
        "id_pdc_itinerance", "id_station_itinerance", "nom_station",
        "nom_amenageur", "nom_operateur",
        "puissance_nominale", "latitude", "longitude",
        "code_insee_commune", "date_mise_en_service", "source","statut_actuel","num_arrondissement"
    ]]


def fusionner_sources(df_belib, df_gireve):
    """Fusionne les deux sources (Gireve et Belib) et retire les éventuels doublons."""
    
    # Concaténation brute des DataFrames
    df = pd.concat([df_belib, df_gireve], ignore_index=True)
    print(f"Lignes issues de la concaténation brute : {len(df)} lignes")
    
    # Dédoublonnage : on garde Belib' en priorité (plus conséquent et déjà optimisé pour Paris)
    # On trie par ordre alphabétique pour que Belib' soit absolument en premier, puis on drop les duplicates
    df = df.sort_values("source", ascending=True) # Belib' en premier dans l'ordre alphabétique
    df = df.drop_duplicates(subset="id_pdc_itinerance", keep="first")
    return df.reset_index(drop=True)

def parser_arrondissement(code_insee):
    """Parse le numéro d'arrondissement depuis un code INSEE parisien."""
    if pd.isna(code_insee):
        return None
    # On retire ce qui est après la virgule au cas où le code INSEE serait un float, puis on vérifie que c'est bien un code INSEE parisien (commençant par 751 et suivi de 2 chiffres), et on extrait le numéro d'arrondissement si c'est valide.
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
    #Extraire le numéro d'arrondissement à partir de l'adresse, en utilisant une expression régulière pour trouver un code postal commençant par 75 suivi de 3 chiffres, puis en vérifiant que les deux derniers chiffres correspondent à un numéro d'arrondissement valide (1 à 20).
    if pd.isna(adresse):
        return None
    
    match = re.search(r"\b(75\d{3})\b", str(adresse))
    if match:
        cp = match.group(1)
        num = int(cp[-2:])
        if 1 <= num <= 20:
            return num
    return None


def recuperer_statuts_pdc_belib(maj_airflow=False):
    """Récupère le statut temps réel des points de charge Belib'."""
    maintenant = datetime.now().replace(minute=0, second=0, microsecond=0)
    if maintenant.hour > 2:
        maintenant = maintenant.replace(hour=maintenant.hour - 2)
    else:
        maintenant = (maintenant - timedelta(days=1)).replace(hour=23)
    plus_tot = maintenant - timedelta(minutes=2)
    fromdate = plus_tot.strftime("%Y-%m-%dT%H:%M:%S")
    todate = maintenant.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"Récupération des statuts Belib' du {fromdate} au {todate}.")

    return collect_data(source="belib_rt", fromdate=fromdate, todate=todate, force=maj_airflow)

def recuperer_liste_stations_belib(maj_airflow=False):
    """Récupère la liste unique des stations Belib' avec statut actuel."""
    print("Récupération des données Belib'.")
    
    listestations = collect_data(source="belib_stat")
    if listestations is None or listestations.empty:
        return None
    listestations["num_arrondissement"] = listestations["adresse_station"].apply(extraire_num_arrondissement)
    listestations = listestations.dropna(subset=["num_arrondissement"])
    listestations["num_arrondissement"] = listestations["num_arrondissement"].astype(int)
    
    # Renommer les colonnes de coordonnées pour plus de clarté
    listestations = listestations.rename(columns={"lat": "latitude", "lon": "longitude"})

    # Remplir le numéro d'arrondissement à partir de l'adresse
    #On supprime les lignes où le numéro d'arrondissement n'a pas pu être extrait, car elles ne seront pas utiles pour l'analyse par arrondissement.
    #Par ailleurs, cela permet aussi de s'assurer que le dataset final ne contient que des stations de recharge situées à Paris, ce qui est l'objectif de notre analyse.
    #On caste le numéro d'arrondissement en entier pour faciliter les opérations de regroupement et d'analyse ultérieures, notamment pour le calcul des taux de disponibilité par arrondissement (pas de float ou de string qui pourraient compliquer les calculs).
    listestations["code_insee_commune"] = listestations["num_arrondissement"].apply(lambda x: f"751{x:02d}")
    #On met à jour le code INSEE de la commune en fonction du numéro d'arrondissement, en utilisant une fonction lambda pour formater correctement le code INSEE (75101 à 75120) à partir du numéro d'arrondissement (1 à 20).
    
    # Pour le statut temps réel, on récupère les données de l'API et on garde uniquement la ligne la plus récente pour chaque enregistrement, afin d'éviter de faire exploser le nombre de lignes lors du merge avec la liste statique des stations et le temps de chargement des données.
    statuts = recuperer_statuts_pdc_belib(maj_airflow)
    if statuts is not None and not statuts.empty:
        # Conversion du timestamp pour pouvoir trier
        statuts["snapshot_at"] = pd.to_datetime(statuts["snapshot_at"])
        
        # Pour chaque id_pdc, on garde donc la ligne la plus récente et on supprime les autres, afin d'avoir un seul statut actuel par point de charge.
        statuts_derniers = (statuts.sort_values("snapshot_at").drop_duplicates(subset="id_pdc", keep="last")[["id_pdc", "statut_pdc"]].rename(columns={"statut_pdc": "statut_actuel"}))
        
        # Merge avec la liste des stations pour ajouter le statut actuel à chaque station, en utilisant une jointure à gauche pour conserver toutes les stations même celles qui n'ont pas de statut temps réel disponible.
        listestations = listestations.merge(statuts_derniers,left_on="id_pdc_local",right_on="id_pdc",how="left")
        listestations["statut_actuel"] = listestations["statut_actuel"].fillna("Inconnu")
    else:
        listestations["statut_actuel"] = "Inconnu"
    
    # Sauvegarde et encodage UTF-8 pour les caractères spéciaux
    listestations.to_csv("./data/belib_paris.csv", index=False, encoding="utf-8-sig")
    listestations = harmoniser_belib(listestations)
    print(f"Nombre d'enregistrements uniques récupérés pour Belib' : {len(listestations)}")
    return listestations

def recuperer_statuts_pdc_gireve():
    #on récupère le statut de disponibilité actualisé de chaque point de charge, en temps réel.
    #Nous ne disposons pas encore du fichier sur le serveur donc nous le récupérons sur le site transports.data.gouv.fr édité par le Ministère des Transports et mis à jour régulièrement.
    maintenant = datetime.now().replace(minute=0, second=0, microsecond=0)
    if maintenant.hour > 2:
        maintenant = maintenant.replace(hour=maintenant.hour - 2)
    else:
        maintenant = (maintenant - timedelta(days=1)).replace(hour=23)
    plus_tot = maintenant - timedelta(minutes=1)
    fromdate = plus_tot.strftime("%Y-%m-%dT%H:%M:%S")
    todate = maintenant.strftime("%Y-%m-%dT%H:%M:%S")
    data = collect_data(source="irve_dyn")
    if data is None or data.empty:
        return pd.DataFrame()
    data = data.rename(columns={"statut_actuel": "occupation_pdc"})
    if "snapshot_at" in data.columns:
        data["snapshot_at"] = pd.to_datetime(data["snapshot_at"])
        data = data.sort_values("snapshot_at").drop_duplicates(subset="id_pdc_itinerance", keep="last")
    print(f"Récupération des statuts IRVE / Gireve du {fromdate} au {todate}.")
    return data

def recuperer_liste_stations_gireve():
      """Récupère la liste des stations IRVE (Gireve) pour Paris."""
      print("Récupération des données IRVE / Gireve.")
      stations_gireve = collect_data(source="irve_conso")

      if stations_gireve is None or stations_gireve.empty:
          print("Aucune donnée IRVE / Gireve disponible.")
          return pd.DataFrame()

      statuts = recuperer_statuts_pdc_gireve()
      if not statuts.empty:
          stations_gireve = stations_gireve.merge(
              statuts,
              left_on='id_pdc_itinerance',
              right_on='id_pdc_itinerance',
              how='left',
          )
          stations_gireve['statut_actuel'] = stations_gireve['occupation_pdc'].fillna("Inconnu")
          stations_gireve = stations_gireve.drop(columns=["etat_pdc", "occupation_pdc"], errors="ignore")
      else:
          stations_gireve['statut_actuel'] = "Inconnu"

      stations_gireve = harmoniser_gireve(stations_gireve)
      stations_gireve.to_csv("./data/gireve_paris.csv", index=False)
      return stations_gireve

def recuperer_vehicules_electriques():
    """Récupère le stock de VE par arrondissement."""
    print("Récupération des données des véhicules électriques.")
    
    # Source 1 : Agence ORE
    url = ("https://opendata.agenceore.fr/api/explore/v2.1/catalog/datasets/"
           "voitures-par-commune-par-energie/exports/csv"
           "?use_labels=false&delimiter=%3B")
    url1 = pd.read_csv(url, sep=";", low_memory=False)
    url1["codgeo"] = url1["codgeo"].astype(str)
    url1 = url1[url1["codgeo"].str.match(r"^751(0[1-9]|1[0-9]|20)$")]
    url1["num_arrondissement"] = url1["codgeo"].str[-2:].astype(int)
    
    

    print(f"Agence ORE : {len(url1)} lignes pour Paris")
    url1.to_csv("./data/vehicules_electriques_paris_ORE.csv", index=False, encoding="utf-8-sig")
    return url1

# Fonction projections
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

def recuperer_population():
    """Récupère le fichier population depuis S3 et le charge en DataFrame."""
    print("Récupération des données population depuis S3.")
    
    try:
        df = lecture_s3("paris_population")
        if df is None or df.empty:
            print("Population : fichier introuvable sur S3 (attendu : raw/data/paris_population.csv)")
            return pd.DataFrame()
        df = df.dropna(subset=["CODGEO"])
        df["num_arrondissement"] = df["CODGEO"].astype(int) - 75100
        df = df[df["num_arrondissement"].between(1, 20)]
        df["pct_majeurs"] = (df["pop_majeurs_18plus"] / df["pop_total"] * 100).round(1)
        print(f"Population : {len(df)} arrondissements")
        return df
    
    except Exception as e:
        print(f"Population pas récupérée sur S3 : {e}")
        return pd.DataFrame()

# Fonction projections
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

    
def enedis_paris_data(annee):
    """Récupère les données de consommation Enedis pour Paris."""
    if S3_BUCKET:
        df = lecture_s3("energie")
        if df is not None:
            return df

    base_url = (
        "https://opendata.enedis.fr/data-fair/api/v1/datasets/"
        "consommation-electrique-par-secteur-dactivite-iris/lines"
    )

    all_data = []
    page = 1
    size = 993

    while True:
        try:
            response = requests.get(base_url, params={
                "qs": f"code_departement:75 AND annee:{annee}",
                "size": size,
                "select": "code_iris,code_commune,nom_commune,code_grand_secteur,conso_totale_mwh,nb_sites",
                "page": page,
            }, timeout=60)
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])

            if not results:
                break

            all_data.extend(results)

            total = data.get("total", 0)
            if len(all_data) >= total:
                break

            page += 1

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                print(f"⚠️ Enedis pagination terminée à la page {page}")
                break
            raise

    df = pd.DataFrame(all_data)
    if "code_iris" in df.columns:
        df["num_arrondissement"] = df["code_iris"].astype(str).str[:5].apply(parser_arrondissement)
    elif "code_commune" in df.columns:
        df["num_arrondissement"] = df["code_commune"].apply(parser_arrondissement)
    print(f"Enedis {annee} : {len(df)} lignes pour Paris, arrondissements uniques : {df['num_arrondissement'].dropna().unique().tolist()}")
    df.to_csv("./data/energie_paris.csv", index=False, encoding="utf-8-sig")
    return df




    


