from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import pandas as pd

Base = declarative_base()


class Borne(Base):
    """Représente un point de charge individuel, toutes sources confondues."""
    __tablename__ = "bornes"
    
    id_pdc_itinerance = Column(String, primary_key=True)
    id_station_itinerance = Column(String, index=True)
    nom_station = Column(String)
    nom_amenageur = Column(String)
    nom_operateur = Column(String)
    puissance_nominale = Column(Float)
    latitude = Column(Float)
    longitude = Column(Float)
    code_insee_commune = Column(String, index=True)
    date_mise_en_service = Column(String)
    source = Column(String)  # belib, gireve, ocm
    statut_actuel = Column(String)
    num_arrondissement = Column(Integer, index=True)
    updated_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<Borne {self.id_pdc_itinerance} | {self.nom_station} | Statut {self.statut_actuel} | Arr. {self.num_arrondissement}>"
    
    @classmethod
    def from_dataframe_row(cls, row):
        """Crée une instance Borne depuis une ligne de DataFrame."""
        return cls(
            id_pdc_itinerance=str(row.get("id_pdc_itinerance")),
            id_station_itinerance=str(row.get("id_station_itinerance")),
            nom_station=row.get("nom_station"),
            nom_amenageur=row.get("nom_amenageur"),
            nom_operateur=row.get("nom_operateur"),
            nbre_pdc=int(row["nbre_pdc"]) if pd.notna(row.get("nbre_pdc")) else None,
            puissance_nominale=float(row["puissance_nominale"]) if pd.notna(row.get("puissance_nominale")) else None,
            latitude=float(row["latitude"]) if pd.notna(row.get("latitude")) else None,
            longitude=float(row["longitude"]) if pd.notna(row.get("longitude")) else None,
            code_insee_commune=str(row.get("code_insee_commune")),
            date_mise_en_service=str(row.get("date_mise_en_service")),
            source=str(row.get("source")),
            statut_actuel=str(row.get("statut_actuel")),
            num_arrondissement=int(row["num_arrondissement"]) if pd.notna(row.get("num_arrondissement")) else None,
            updated_at=datetime.now()
        )


class ParcVehiculesElectriques(Base):
    """Stock de véhicules électriques par arrondissement et trimestre."""
    __tablename__ = "vehicules_electriques"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    num_arrondissement = Column(Integer, index=True)
    date_arrete = Column(String)
    nb_ve = Column(Integer)
    nb_vp_total = Column(Integer)
    taux_ve = Column(Float)

    def __repr__(self):
        return f"<ParcVehiculesElectriques {self.id} | Trim {self.date_arrete} | Arr. {self.num_arrondissement} |Taux % {self.taux_ve}>"

    @classmethod
    def from_dataframe_row(cls, row):
        """Crée une instance ParcVehiculesElectriques depuis une ligne de DataFrame."""
        return cls(
            num_arrondissement=int(row["num_arrondissement"]) if pd.notna(row.get("num_arrondissement")) else None,
            date_arrete=str(row.get("date_arrete")) if pd.notna(row.get("date_arrete")) else None,
            nb_ve=int(row["nb_ve"]) if pd.notna(row.get("nb_ve")) else None,
            nb_vp_total=int(row["nb_vp_total"]) if pd.notna(row.get("nb_vp_total")) else None,
            taux_ve=float(row["taux_ve"]) if pd.notna(row.get("taux_ve")) else None
        )
    
class Pression(Base):
    """Score de pression calculé par arrondissement."""
    __tablename__ = "pression"
    
    num_arrondissement = Column(Integer, primary_key=True)
    nb_ve = Column(Integer)
    nb_vp_total = Column(Integer)
    nb_pdc = Column(Integer)
    pression = Column(Float)
    taux_ve = Column(Float)
    taux_disponibilite = Column(Float)
    updated_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<Pression {self.pression} | Arr. {self.num_arrondissement} |Nb VE {self.nb_ve}>"

    @classmethod
    def from_dataframe_row(cls, row):
        """Crée une instance ParcVehiculesElectriques depuis une ligne de DataFrame."""
        return cls(
            num_arrondissement=int(row["num_arrondissement"]) if pd.notna(row.get("num_arrondissement")) else None,
            nb_ve=int(row["nb_ve"]) if pd.notna(row.get("nb_ve")) else None,
            nb_vp_total=int(row["nb_vp_total"]) if pd.notna(row.get("nb_vp_total")) else None,
            nb_pdc=int(row["nb_pdc"]) if pd.notna(row.get("nb_pdc")) else None,
            pression=float(row["pression"]) if pd.notna(row.get("pression")) else None,
            taux_ve=float(row["taux_ve"]) if pd.notna(row.get("taux_ve")) else None,
            taux_disponibilite=float(row["taux_disponibilite"]) if pd.notna(row.get("taux_disponibilite")) else None,
            updated_at = datetime.now()
        )

class Energie(Base):
    """Conso électrique par secteur IRIS et arrondissement."""
    __tablename__ = "energie"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_commune = Column(String)
    nom_commune = Column(String)
    code_grand_secteur = Column(String)
    conso_totale_mwh = Column(Float)
    nb_sites = Column(Integer)
    num_arrondissement = Column(Integer, index=True)

    def __repr__(self):
        return f"<Energie {self.conso_totale_mwh} MWh | Arr. {self.num_arrondissement}>"

class Population(Base):
    """Population par arrondissement — source INSEE 2021."""
    __tablename__ = "population"
    
    num_arrondissement = Column(Integer, primary_key=True)
    codgeo = Column(String)
    pop_total = Column(Integer)
    pop_majeurs_18plus = Column(Integer)
    pop_mineurs_0_17 = Column(Integer)
    pct_majeurs = Column(Float)
    
    def __repr__(self):
        return f"<Population {self.num_arrondissement}e | {self.pop_total} hab.>"
