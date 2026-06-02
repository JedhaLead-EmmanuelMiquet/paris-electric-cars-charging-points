"""
Script d'initialisation de la base de données.
Exécuté une fois au démarrage du conteneur avant Streamlit.
Récupère les données depuis Airflow / APIs publiques et peuple bornes.db.
"""
import os
import sys
import pandas as pd
import database
import etl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)


def calculer_pression(df_bornes, df_vehicules):
    dernier_trimestre = df_vehicules["date_arrete"].max()
    ve_derniers = df_vehicules[df_vehicules["date_arrete"] == dernier_trimestre]

    ve_par_arr = ve_derniers.groupby("num_arrondissement").agg(
        nb_ve=("nb_vp_rechargeables_el", "sum"),
        nb_vp_total=("nb_vp", "sum"),
    ).reset_index()

    bornes_par_arr = (
        df_bornes.groupby("num_arrondissement")
        .agg(nb_pdc=("id_pdc_itinerance", "count"))
        .reset_index()
    )

    pression = ve_par_arr.merge(bornes_par_arr, on="num_arrondissement", how="left")
    pression["nb_pdc"] = pression["nb_pdc"].fillna(0)
    pression["pression"] = (pression["nb_ve"] / pression["nb_pdc"]).round(1)
    pression["taux_ve"] = (pression["nb_ve"] / pression["nb_vp_total"] * 100).round(1)
    pression = pression.sort_values("pression", ascending=False)
    return pression


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
                    "arr_num": arr,
                    "scenario": scenario,
                    "horizon_years": horizon,
                    "ve_actuel": int(nb_ve),
                    "ve_projete": ve_proj,
                    "bornes_actuelles": int(nb_pdc),
                    "bornes_cible": bornes_cible,
                    "deficit_bornes": deficit,
                    "pression_projetee": pression_proj,
                    "energie_add_mwh": round(deficit * 2.5, 1),
                })
                total_deficit += deficit
            lignes_paris.append({
                "scenario": scenario,
                "horizon_years": horizon,
                "deficit_total": total_deficit,
            })

    return pd.DataFrame(lignes_arrdt), pd.DataFrame(lignes_paris)


def run():
    print("=== Initialisation de la base de données ===")

    # 1. Bornes
    print("[1/5] Récupération des stations Belib'...")
    stations_belib = etl.recuperer_liste_stations_belib()
    print("[2/5] Récupération des stations IRVE/Gireve...")
    stations_gireve = etl.recuperer_liste_stations_gireve()

    if (stations_belib is None or stations_belib.empty) and (stations_gireve is None or stations_gireve.empty):
        print("AVERTISSEMENT : aucune station récupérée — Streamlit démarrera sans données de bornes.")
        # On continue quand même pour que Streamlit puisse afficher un message d'erreur clair

    stations_belib = stations_belib if stations_belib is not None else pd.DataFrame()
    stations_gireve = stations_gireve if stations_gireve is not None else pd.DataFrame()
    listestations = etl.fusionner_sources(stations_belib, stations_gireve)
    print(f"  → {len(listestations)} points de charge au total")
    database.sauvegarder_totalite_bornes(listestations)

    # 2. Véhicules électriques
    print("[3/5] Récupération des véhicules électriques (Agence ORE)...")
    liste_ve = etl.recuperer_vehicules_electriques()
    if liste_ve is not None and not liste_ve.empty:
        database.sauvegarder_parc_vehicules(liste_ve)

    # 3. Pression
    if liste_ve is not None and not liste_ve.empty:
        print("[4/5] Calcul de la pression par arrondissement...")
        pression = calculer_pression(listestations, liste_ve)
        database.sauvegarder_pression(pression)
    else:
        pression = pd.DataFrame()
        print("[4/5] Pression ignorée (pas de données VE).")

    # 4. Énergie
    print("[5/5] Récupération des données énergie (Enedis)...")
    energie = etl.enedis_paris_data(2022)
    if energie is not None and not energie.empty:
        database.sauvegarder_energie(energie)
        energie_par_arr = energie.groupby("num_arrondissement").agg(
            conso_totale_mwh=("conso_totale_mwh", "sum"),
            nb_sites=("nb_sites", "sum"),
        ).reset_index()
    else:
        energie_par_arr = pd.DataFrame()
        print("  → Données énergie non disponibles.")

    # 5. Population
    print("[+] Récupération de la population (INSEE)...")
    population = etl.recuperer_population()
    if population is not None and not population.empty:
        database.sauvegarder_population(population)

    # 6. Projections
    if not pression.empty:
        print("[+] Calcul des projections déficitaires...")
        df_arrdt, df_paris = calculer_projections(pression)
        database.sauvegarder_projections(df_arrdt, df_paris)
        df_arrdt.to_csv(os.path.join(BASE_DIR, "data", "energie_by_arrdt.csv"), index=False)
        df_paris.to_csv(os.path.join(BASE_DIR, "data", "soutenabilite_scenarios.csv"), index=False)

    print("=== Base de données initialisée avec succès ===")


if __name__ == "__main__":
    run()
