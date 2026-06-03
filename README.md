---
title: Bornes VE Paris
emoji: ⚡
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8501
tags:
  - streamlit
  - data-visualization
  - electric-vehicles
  - paris
pinned: false
short_description: Bornes de recharge VE à Paris
---

# ⚡ Paris Electric Cars Charging Points

Jedha Data Science Lead's Bootcamp Final Project

## Purpose

Tableau de bord interactif pour analyser et prioriser l'installation de bornes de recharge pour véhicules électriques à Paris.

## Setup

### Secrets (HF Spaces → Settings → Variables and secrets)

| Nom | Description |
|-----|-------------|
| `ALH_EMAIL` | Email Airflow (ac.mbepa@gmail.com) |
| `ALH_PASSWORD` | Mot de passe Airflow |
| `S3_BUCKET` | Nom du bucket AWS S3 (optionnel) |
| `AWS_REGION` | Région AWS (ex: eu-north-1) |
| `AWS_ACCESS_KEY_ID` | Clé d'accès AWS (si S3 utilisé) |
| `AWS_SECRET_ACCESS_KEY` | Clé secrète AWS (si S3 utilisé) |

### Fonctionnement

Au démarrage du conteneur, le script ETL (`bornes_arrondissements.py`) récupère automatiquement les données depuis l'API Airflow et les APIs publiques (Enedis, Agence ORE), puis initialise la base SQLite locale avant de lancer Streamlit.
