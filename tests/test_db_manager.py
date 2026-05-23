import pytest
import pandas as pd

from inatdatapipeline.db_manager import DBManager

db_file = "tests/test.db"
experts_file = "data/experts/Master_iNaturalist_US_Canada_Experts_20240327.csv"

def test_setup_db():
    manager = DBManager(db_file)
    manager.connect()
    manager.setup_db()


def test_get_mappings():
    manager = DBManager(db_file)
    with manager as db:
        db.setup_db()
        df = db.get_mappings()
    
    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Mappings: \n\n{df}")
    print("-------------------------------------------")


def test_get_inat_taxa():
    manager = DBManager(db_file)
    with manager as db:
        df = db.get_inat_taxa()
    
    print(f"\n\n")
    print("-------------------------------------------")
    print(f"iNat Taxa: \n\n{df}\n")
    df.info()
    print("-------------------------------------------")


def test_expert_identifications():
    manager = DBManager(db_file)
    with manager as db:
        expert_ids_df = db.get_expert_identifications()
        experts_df = db._select_query("SELECT * FROM experts;")
        identifications_df = db._select_query("SELECT * FROM identifications")

    if len(experts_df) > 0 and len(identifications_df) > 0:
        assert len(expert_ids_df) > 0

    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Expert Identifications: \n\n{expert_ids_df.head(10)}\n")
    expert_ids_df.info()
    print("-------------------------------------------")


def test_update_experts():
    manager = DBManager(db_file)
    experts_df = pd.read_csv(experts_file)
    experts_df = experts_df.dropna(subset=["iNaturalist_id"])
    
    with manager as db:
        count = db.update_experts(experts_df)
    
    assert len(experts_df) == count


def test_get_full_observations():
    manager = DBManager(db_file)
    with manager as db:
        df = manager.get_full_observations()
    
    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Full Observations: \n\n{df.head(10)}")
    print("-------------------------------------------")

    df.to_csv("data/output/full_observations.csv", index=False)