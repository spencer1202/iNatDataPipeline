"""
iNaturalist API observations download for tracked species
"""
import pandas as pd
import datetime as dt
import logging
from configparser import ConfigParser
import requests
import prison
import json
import time

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
                Reads from "observations" section to get place ID, quality grades, records per page, observation fields JSON file, and 
                taxon batch size.
        """

        try:
            self.db_manager     = db_manager                                        # Database manager object
            self.place_id       = int(config["observations"]["place_id"])           # Place ID to filter search (e.g. Oregon = 10)
            self.per_page       = int(config["observations"]["per_page"])           # Number of records to return per request
            self.batch_size     = int(config["observations"]["batch_size"])         # Taxon ID batch size for querying observations
            self.quality_grade  = config["observations"]["quality_grade"]           # iNaturalist quality grade filter(s)
                                                                                    # Comma separated (e.g. "research" or "research,casual")
            self.fields_json    = config["observations"]["fields_json"]             # JSON file with the observation fields to query for
            self.update_days    = int(config["observations"]["update_before_days"]) # Only query for taxa that were last updated at least 
                                                                                    # this many days ago
        
        except TypeError:
            logger.error("Malformed observation configuration options (could not convert to integer).")
            raise
        except KeyError:
            logger.error("Malformed observation configuration options (missing section or field).")
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


    def fetch_pages(self, observations: list, params: dict, headers: str) -> list:
        url = "https://api.inaturalist.org/v2/observations"
        
        page = 1
        while True:
            params["page"] = page
            try:
                response = requests.get(
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                observations.extend(results)
                time.sleep(0.5)

                if len(results) < self.per_page:
                    break
                page += 1
                time.sleep(0.5)
                
            except requests.Timeout:
                logger.error(f"Request for taxon {params["taxon_id"]} timed out.")
        
        return observations
            

    def download_observations(self, ids: list, params: dict, headers: str) -> list:
        print(f"Downloading batch:\n{ids}\n")

        observations = []
        params["taxon_id"] = ",".join(str(id) for id in ids)
        observations = self.fetch_pages(observations, params, headers)
        
        return observations

            
    


    def get_observations(self, auth: iNaturalistAuth):
        """
        Downloads observations from iNaturalist using the iNaturalist taxon IDs in the local database.
        """
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

        # Get query fields in RISON format from JSON file
        try:
            with open(self.fields_json, "r") as fp:
                fields_dict = json.load(fp)
            base_params["fields"] = prison.dumps(fields_dict)
        except:
            logger.error(f"Failed to load query observation fields from file: {self.fields_json}.")
            return

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
                for result in results:
                    print(result)
            