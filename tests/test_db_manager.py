import pytest
import pandas as pd

from pipeline.db_manager import DBManager

db_file = "inat.db"

def test_setup_db():
    manager = DBManager(db_file)
    manager.connect()
    manager.setup_db()


def test_get_mappings():
    manager = DBManager(db_file)
    manager.connect()
    df = manager.get_mappings()
    print(df)
    print(f"\n\nMappings: \n{df}")


def test_get_inat_taxa():
    manager = DBManager(db_file)
    with manager as db:
        df = db.get_inat_taxa()
    print(f"\n\niNat Taxa: \n{df}")