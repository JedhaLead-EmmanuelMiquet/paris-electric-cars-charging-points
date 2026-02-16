import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Borne, ParcVehiculesElectriques, Pression, Energie, Population

DB_PATH = "./bornes.db"

def get_engine():
    """Connexion à la base de données"""
    return create_engine(f"sqlite:///{DB_PATH}", echo=False)

def init_db():
    """Créer les tables si elles n'existent pas."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    print(f"Base de données initialisée : {DB_PATH}")
    return engine

def get_session():
    """Initialiser la session"""
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()

def sauvegarder_bornes(df):
    """Insérer ou mettre à jour les points de charge (ou bornes) depuis notre DataFrame harmonisé."""
    engine = init_db()
    session = get_session()
    
    compteur = {"insert": 0, "update": 0}
    
    #Pour chaque point de charge dans le DataFrame vérifie si la donnée existe déjà en base : si oui on met à jour, si non on insère
    for _, row in df.iterrows():
        existante = session.get(Borne, str(row["id_pdc_itinerance"]))
        
        if existante:
            # Mise à jour
            existante.statut_actuel = str(row.get("statut_actuel", "Inconnu"))
            existante.updated_at = pd.Timestamp.now()
            compteur["update"] += 1
        else:
            # Insertion
            borne = Borne.from_dataframe_row(row)
            session.add(borne)
            compteur["insert"] += 1
    
    session.commit()
    session.close()
    print(f"Points de charge sauvegardés : {compteur['insert']} PDC insérés, {compteur['update']} PDC mis à jour")

def sauvegarder_totalite_bornes(df):
    """Version rapide : écrase la table et réinsère tout."""
    engine = init_db()
    df.to_sql("bornes", engine, if_exists="replace", index=False)
    print(f"{len(df)} points de charge sauvegardés en base")

def sauvegarder_pression(df_pression):
    """Sauvegarde le score de pression par arrondissement."""
    engine = init_db()
    df_pression.to_sql("pression", engine, if_exists="replace", index=False)
    print(f"Score de pression sauvegardé pour {len(df_pression)} arrondissements")

def sauvegarder_energie(df_energie):
    """Sauvegarde conso par arrondissement."""
    engine = init_db()
    df_energie.to_sql("energie", engine, if_exists="replace", index=False)
    print(f"Score de pression sauvegardé pour {len(df_energie)} arrondissements")

def sauvegarder_parc_vehicules(df_ve):
    """Sauvegarde le parc de VE par arrondissement."""
    engine = init_db()
    df_ve.to_sql("vehicules_electriques", engine, if_exists="replace", index=False)
    print(f"{len(df_ve)} enregistrements VE sauvegardés")

def charger_bornes():
    """Charge les bornes depuis la base et vers un nouveau DataFrame."""
    engine = get_engine()
    return pd.read_sql("SELECT * FROM bornes", engine)

def charger_pression():
    """Charge le score de pression depuis la base et vers un nouveau DataFrame."""
    engine = get_engine()
    return pd.read_sql("SELECT * FROM pression", engine)

def sauvegarder_projections(df_arrdt, df_paris):
    engine = init_db()
    df_arrdt.to_sql("projections_arrdt", engine, if_exists="replace", index=False)
    df_paris.to_sql("projections_paris", engine, if_exists="replace", index=False)
    print(f"Projections sauvegardées : {len(df_arrdt)} lignes arrdt, {len(df_paris)} lignes Paris")

def sauvegarder_population(df):
    engine = init_db()
    df.to_sql("population", engine, if_exists="replace", index=False)
    print(f"Population sauvegardée : {len(df)} arrondissements")

def sauvegarder_projections(df_arrdt, df_paris):
    engine = init_db()
    df_arrdt.to_sql("projections_arrdt", engine, if_exists="replace", index=False)
    df_paris.to_sql("projections_paris", engine, if_exists="replace", index=False)
    print(f"Projections sauvegardées")

def charger_energie_population():
    engine = get_engine()
    return pd.read_sql("""
        SELECT 
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

def requete_select(sql):
    """Exécute une requête SQL et retourne un DataFrame."""
    engine = get_engine()
    return pd.read_sql(sql, engine)
