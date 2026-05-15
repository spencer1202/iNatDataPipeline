import pytest
import pandas as pd
from configparser import ConfigParser
import numpy as np
import logging
import os

from pipeline.observations import ObservationQuery
from pipeline.db_manager import DBManager
from pipeline.inaturalist_auth import iNaturalistAuth

db_file = "tests/test_small.db"
base_config = ConfigParser()
base_config["observations"] = {
        "place_id": 10,
        "quality_grade": "research",
        "per_page": 200,
        "batch_size": 5,
        "fields_json": r"pipeline/obs_fields.json",
        "update_before_days": 30,
        "project_id": 247148
    }
username = "hspencer1202"

# Set up logging
log_folder = "logs"
log_file = "observations_test.log"
if not os.path.exists("logs"):
    os.mkdir("logs")
logger = logging.getLogger('pipeline')
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

file_handler = logging.FileHandler(os.path.join(log_folder, log_file))
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M"))

logger.addHandler(console_handler)
logger.addHandler(file_handler)

def test_get_observations():
    manager = DBManager(db_file)
    auth = iNaturalistAuth()
    auth.generate_access_token(username)

    querier = ObservationQuery(manager, base_config)
    querier.get_observations(auth)


def test_date_taxon_map():
    manager = DBManager(db_file)
    with manager as db:
        taxa_df = db.get_inat_taxa()

    taxa_df["date_updated"] = np.where(
        taxa_df["taxon_id"] < 500000,
        "2026-13-5",
        taxa_df["date_updated"]
    )
    # print(taxa_df["date_updated"])
    date_taxon_map = ObservationQuery.create_date_taxon_map(taxa_df)
    assert len(date_taxon_map["2026-13-5"]) == len(taxa_df[taxa_df["taxon_id"] < 500000])


def test_batches():
    manager = DBManager(db_file)
    with manager as db:
        taxa_df = db.get_inat_taxa()
    
    taxa_df["date_updated"] = np.where(
        taxa_df["taxon_id"] < 500000,
        "2026-13-5",
        taxa_df["date_updated"]
    )
    batch_size = 50
    date_taxa_map = ObservationQuery.create_date_taxon_map(taxa_df)
    for date, ids in date_taxa_map.items():
        batches = ObservationQuery.get_batches(list(ids), batch_size)
        # print(f"Processing taxa filtered by date: {date}")
        for i, batch in enumerate(batches):
            assert len(batch) <= batch_size
            # print(f"Batch #{i}: {batch}")


def test_observation_results():
    observations_df = pd.read_csv("output/observations.csv")
    identifications_df = pd.read_csv("output/identifications.csv")
    users_df = pd.read_csv("output/users.csv")

    print(f"Observations DF info:\n{observations_df.info()}\n")
    print(f"Identifications DF info:\n{identifications_df.info()}\n")
    print(f"Users DF info:\n{users_df.info()}\n")

    print(f"Observations in ORBIC project: {len(observations_df[observations_df["in_project"] == True])}")