import pytest
import pandas as pd
from configparser import ConfigParser
import numpy as np
import logging
import os

from src.inatdatapipeline.observations import ObservationQuery
from src.inatdatapipeline.db_manager import DBManager
from src.inatdatapipeline.inaturalist_auth import iNaturalistAuth


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger('pipeline')
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

logger.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_date_taxon_map():
    manager = DBManager(db_file)
    with manager as db:
        db.setup_db()
        taxa_df = db.get_inat_taxa()

    taxa_df["date_updated"] = np.where(
        taxa_df["taxon_id"] < 500000,
        "2026-5-12",
        taxa_df["date_updated"]
    )

    date_taxon_map = ObservationQuery.create_date_taxon_map(taxa_df)
    assert len(date_taxon_map.get("2026-5-12", ())) == len(taxa_df[taxa_df["taxon_id"] < 500000])


def test_batches():
    manager = DBManager(db_file)
    with manager as db:
        taxa_df = db.get_inat_taxa()
    
    taxa_df["date_updated"] = np.where(
        taxa_df["taxon_id"] < 500000,
        "2026-5-12",
        taxa_df["date_updated"]
    )
    batch_size = 50
    date_taxa_map = ObservationQuery.create_date_taxon_map(taxa_df)
    for date, ids in date_taxa_map.items():
        batches = ObservationQuery.get_batches(list(ids), batch_size)
        for i, batch in enumerate(batches):
            assert len(batch) <= batch_size


@pytest.mark.skip()
def test_observation_results():
    observations_df = pd.read_csv("data/output/observations.csv")
    identifications_df = pd.read_csv("data/output/identifications.csv")
    users_df = pd.read_csv("data/output/users.csv")

    print(f"\nObservations DF info:")
    observations_df.info()
    print(f"\nIdentifications DF info:")
    identifications_df.info()
    print(f"\nUsers DF info:")
    users_df.info()

    print(f"Observations in ORBIC project: {len(observations_df[observations_df["in_project"] == True])}")