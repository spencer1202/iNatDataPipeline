"""
iNaturalist API observations download for tracked species
"""
import pandas as pd
import datetime as dt
import logging

from db_manager import DBManager
import helpers
from helpers import iNaturalistAuth

logger = logging.getLogger('pipeline')

class ObservationQuery:

    def __init__(self, db_manager: DBManager, auth: iNaturalistAuth, batch_size: int):
        self.db_manager = db_manager

    
    def _get_batches(self, full_list: list, batch_size: int):
        """Helper function to yield successive n-sized chunks from lst"""
        for i in range(0, len(full_list), n):
            yield full_list[i:i + batch_size]


    def download_observations(self, taxa_df: pd.DataFrame, auth: iNaturalistAuth):
        if not auth.get_access_token():
            logger.error("No access token in authentication object")
            raise ValueError
        
        headers = auth.get_auth_headers()
        
        

        
        

    def run_queries(self, taxa_df: pd.DataFrame, created_after: dt.date):
        """
        Fetches observations for the taxa in taxa_df that were created after the given date.
        """
        batches = list(self._get_batches())
        params = {
            "taxon_id": ",".join(taxon_ids),
            "created_d1": 
        }
        while True:
            results = fetch_page(params)
            if len(results) < per_page

    def fetch_page(self, params):
        pass