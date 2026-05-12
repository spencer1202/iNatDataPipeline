import pytest
import pandas as pd

from pipeline.db_manager import DBManager

db_file = "inat.db"

def test_update_tracking():
    tracking_df = pd.read_csv("taxonomy/tracking_lists/medium_list.csv")
    colnames = {
        "ELCODE": "elcode",
        "ELEMENT_SUBNATIONAL_ID": "est_id",
        "SNAME": "sname",
        "SCOMNAME": "scomname"
    }
    tracking_df = tracking_df.rename(columns=colnames)
    print(tracking_df)
    print(tracking_df.info())
    manager = DBManager(db_file)
    manager.connect()
    manager.update_tracking(tracking_df)
    manager.commit()

