import pytest
import pandas as pd

from pipeline.db_manager import DBManager

db_file = "inat.db"

def test_setup_db():
    manager = DBManager(db_file)
    manager.connect()
    manager.setup_db()

def test_update_tracking():
    tracking_df = pd.read_csv("taxonomy/tracking_lists/all_tracked.csv")
    colnames = {
        "ELCODE": "elcode",
        "ELEMENT_SUBNATIONAL_ID": "est_id",
        "SNAME": "sname",
        "SCOMNAME": "scomname"
    }
    tracking_df = tracking_df.rename(columns=colnames)
    #print(tracking_df)
    #print(tracking_df.info())
    manager = DBManager(db_file)
    manager.connect()
    manager.update_tracking(tracking_df)
    manager.commit()

def test_insert_overrides():
    overrides_df = pd.read_csv("taxonomy/name_maps/name_overrides.csv")
    
    manager = DBManager(db_file)
    manager.connect()
    count = manager.insert_overrides(overrides_df)
    print("count:", count)


def test_get_mappings():
    manager = DBManager(db_file)
    manager.connect()
    df = manager.get_mappings()
    print(df)