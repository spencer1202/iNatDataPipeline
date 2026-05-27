import pytest
import pandas as pd
from configparser import ConfigParser
import numpy as np
import logging
import os

from inatdatapipeline.observations import ObservationQuery, ObservationsResult
from inatdatapipeline.db_manager import DBManager
from inatdatapipeline.request_helpers import INaturalistAuth
import inatdatapipeline.config as config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_date_taxon_map(core_cfg):
    manager = DBManager(core_cfg.db_file)
    with manager as db:
        db.setup_db()
        taxa_df = db.get_inat_taxa()

    taxa_df["date_updated"] = np.where(
        taxa_df["taxon_id"] < 500000,
        "2026-5-12",
        taxa_df["date_updated"]
    )

    date_taxon_map = ObservationQuery._create_date_taxon_map(taxa_df)
    assert len(date_taxon_map.get("2026-5-12", ())) == len(taxa_df[taxa_df["taxon_id"] < 500000])


def test_batches(core_cfg, obs_cfg):
    manager = DBManager(core_cfg.db_file)
    with manager as db:
        taxa_df = db.get_inat_taxa()
    
    taxa_df["date_updated"] = np.where(
        taxa_df["taxon_id"] < 500000,
        "2026-5-12",
        taxa_df["date_updated"]
    )

    date_taxa_map = ObservationQuery._create_date_taxon_map(taxa_df)
    for date, ids in date_taxa_map.items():
        batches = ObservationQuery._get_batches(list(ids), obs_cfg.batch_size)
        for i, batch in enumerate(batches):
            assert len(batch) <= obs_cfg.batch_size


def test_fetch_observations(observation_results):
    results: ObservationsResult = observation_results["results"]
    assert results is not None

    observations_df = pd.DataFrame(results.observations)
    identifications_df = pd.DataFrame(results.identifications)
    users_df = pd.DataFrame(results.users)
    completed_taxa = results.completed_taxa

    print(observations_df[~observations_df["taxon_id"].isin(completed_taxa)])
    # assert len(observations_df[observations_df["taxon_id"].isin(completed_taxa)]) == len(observations_df)

    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Observations: \n\n{observations_df}")
    print("-------------------------------------------")

    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Identifications: \n\n{identifications_df}")
    print("-------------------------------------------")

    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Users: \n\n{users_df}")
    print("-------------------------------------------")