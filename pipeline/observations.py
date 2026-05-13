"""
iNaturalist API observations download for tracked species
"""
import pandas as pd
import datetime as dt
import logging
from configparser import ConfigParser

from db_manager import DBManager
import helpers
from helpers import iNaturalistAuth

logger = logging.getLogger('pipeline')

class ObservationQuery:

    def __init__(self, db_manager: DBManager, config: ConfigParser):
        """
        Create object for pulling observations from iNaturalist API.
        Args:
            db_manager:
                Database manager object for accessing the local database
            config:
                ConfigParser object to get configuration options from. 
                Reads from "observations" section to get place ID, quality grades, records per page, and 
                taxon batch size.
        """
        self.db_manager = db_manager
        try:
            self.place_id        = int(config["observations"]["place_id"])
            self.quality_grade   = config["observations"]["quality_grade"]
            self.per_page        = int(config["observations"]["per_page"])
            self.batch_size      = int(config["observations"]["batch_size"])
        except TypeError:
            logger.error("Malformed observation configuration options.")
            raise


    @staticmethod
    def get_batches(full_list: list, batch_size: int):
        """Helper function to yield successive n-sized chunks from lst"""
        for i in range(0, len(full_list), batch_size):
            yield full_list[i:i + batch_size]     
        
    def fetch_page(self, params):
        pass

    def run_queries(self, taxa: set, params: dict, per_page: int):
        """
        Fetches observations for the taxa in taxa_df that were created after the given date.
        """
        batches = list(self._get_batches())

        while True:
            results = self.fetch_page(params)
            if len(results) < per_page:
                pass


    @staticmethod
    def create_date_taxon_map(taxa_df: pd.DataFrame) -> dict:
        """
        Creates a map that groups taxon_ids into sets with date_updated as the key.
        """
        date_taxon_map = taxa_df.groupby("date_updated")["taxon_id"].apply(set).to_dict()
        date_taxon_map["None"] = set(taxa_df[taxa_df["date_updated"].isna()]["taxon_id"])
        return date_taxon_map


    def download_observations(self, ids: list, params: dict, headers: str):
        print(f"Downloading batch:\n{ids}\n")
    


    def get_observations(self, auth: iNaturalistAuth):
        """
        Downloads observations from iNaturalist using the iNaturalist taxon IDs in the local database.
        """
        # Get configurations

       
        # Set up authentication
        if not auth.get_access_token():
            logger.error("No access token in authentication object")
            raise ValueError
        headers = auth.get_auth_headers()

        # Configure base parameters
        base_params = {
            'place_id': self.place_id,
            'quality_grade': self.quality_grade,
            'per_page': self.per_page,
            'order_by': 'created_at',
            'order': 'desc',
        }

        # Get iNat taxa from database
        with self.db_manager as db:
            taxa_df = db.get_inat_taxa()
        
        if len(taxa_df) == 0:
            logger.error("iNaturalist taxa mapping table is empty.")
            return

        date_taxa_map = ObservationQuery.create_date_taxon_map(taxa_df)

        for date, ids in date_taxa_map.items():
            batches = ObservationQuery.get_batches(list(ids), self.batch_size)
            print(f"Processing taxa filtered by date: {date}")
            if date != "None":
                base_params['created_d1'] = date
            
            for i, batch in enumerate(batches, start=1):
                results = self.download_observations(batch, base_params, headers)
            