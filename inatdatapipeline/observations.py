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

from .db_manager import DBManager
from .inaturalist_auth import iNaturalistAuth

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
            self.project_id     = int(config["observations"]["project_id"])         # iNaturalist project ID to check for
        
        except TypeError:
            logger.error("Malformed observation configuration options (could not convert to integer).")
            raise
        except KeyError:
            logger.error("Malformed observation configuration options (missing section or field).")
            raise


    @staticmethod
    def get_batches(full_list: list, batch_size: int):
        """Helper function to yield successive n-sized chunks from list"""
        for i in range(0, len(full_list), batch_size):
            yield full_list[i:i + batch_size]


    @staticmethod
    def create_date_taxon_map(taxa_df: pd.DataFrame) -> dict:
        """
        Creates a map that groups taxon_ids into sets with date_updated as the key.
        """
        date_taxon_map = taxa_df.groupby("date_updated")["taxon_id"].apply(set).to_dict()
        date_taxon_map["None"] = set(taxa_df[taxa_df["date_updated"].isna()]["taxon_id"])
        return date_taxon_map
            

    @staticmethod
    def download_observations(ids: list, params: dict, headers: str) -> list:
        observations = []
        params["taxon_id"] = ",".join(str(id) for id in ids)
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

                if len(results) < params["per_page"]:
                    break
                page += 1
                time.sleep(0.5)
                
            except requests.Timeout:
                logger.error(f"Request for taxon {params["taxon_id"]} timed out.")
            except:
                logger.error(f"Unknown error occurred while dowloading observations.")

        logger.debug(f"\tFinished downloading {len(observations)} results.")
        return observations


    def add_records_from_result(self, result: list, user_set: set):
        """
        Takes the JSON response dictionary for one observation and extracts the observation information and
        a list of its identifications and associated users.
        
        Args:
            result:
                A dictionary representing one observation retrieved from the API response.
            user_set:
                Set of user IDs that have already been encountered.
        Returns:
            observations:
            identifications:
            users:
            
        """
        identifications = []
        new_users = []
        observation = {
            "observation_id"                : result.get("id"),
            "observer_id"                   : result.get("user", {}).get("id"),
            "taxon_id"                      : result.get("community_taxon_id"),
            "license"                       : result.get("license_code"),
            "latitude_public"               : result.get("geojson", {}).get("coordinates", [None, None])[0],
            "longitude_public"              : result.get("geojson", {}).get("coordinates", [None, None])[1],
            "latitude_private"              : result.get("private_geojson", {}).get("coordinates", [None, None])[0],
            "longitude_private"             : result.get("private_geojson", {}).get("coordinates", [None, None])[1],
            "coordinate_precision"          : result.get("positional_accuracy"),
            "coordinate_precision_public"   : result.get("public_positional_accuracy"),
            "observed_on"                   : result.get("observed_on"),
            "observed_on_string"            : result.get("observed_on_string"),
            "created_at"                    : result.get("created_at"),
            "quality_grade"                 : result.get("quality_grade"),
            "url"                           : result.get("uri"),
            "description"                   : result.get("description"),
            "id_agreements"                 : result.get("num_identification_agreements"),
            "id_disagreements"              : result.get("num_identification_disagreements"),
            "captive_cultivated"            : result.get("captive"),
            "place_guess_public"            : result.get("place_guess"),
            "place_guess_private"           : result.get("place_guess_private"),
            "obscured"                      : result.get("obscured"),
            "in_project"                    : True if self.project_id in result.get("project_ids", []) else False
        }

        # Get user who made the observation, add to user set if not already present
        obs_user = result.get("user", {})
        obs_user_id = obs_user.get("id")

        if obs_user_id and obs_user_id not in user_set:
            user_set.add(obs_user_id)
            new_users.append(obs_user)
        
        # Get identifications and identifying users
        identifications, ident_users = ObservationQuery.get_identifications(
            observation["observation_id"], 
            result.get("identifications"),
            user_set
        )
        new_users.extend(ident_users)

        logger.debug(f"  [ Observation {observation["observation_id"]:>10} ]  Identifications: {len(identifications):<2}  New users: {len(new_users)}")

        return observation, identifications, new_users


    @staticmethod
    def get_identifications(observation_id: int, ident_list: list, user_set: set) -> tuple[list, list]:
        """
        Extracts dictionaries of identifications and new users from an observation's identification list.

        Args:
            observation_id:
                The id of this observation, which will be added to the identification record as a foreign key.
            ident_list:
                List of identification objects from the JSON response for this observation
            user_set:
                Set of user IDs that have already been encountered.
        Returns:
            (identifications, users):
                A tuple of two lists: a list of dictionaries with identifications for this observation, and
                a list of dictionaries with the users who made the identifications (only 
                including users not yet in the user_set).
        """
        if not ident_list:
            return [], []
        
        identifications = []
        users = []
        
        for identification in ident_list:
            user = identification.get("user", {})
            user_id = user.get("id")
            new_identificaion = {
                "observation_id"    : observation_id,
                "user_id"           : user_id,
                "identification_id" : identification.get("id"),
                "created_at"        : identification.get("created_at"),
                "current"           : identification.get("current"),
                "taxon_id"          : identification.get("taxon", {}).get("id")
            }
            if user_id and user_id not in user_set:
                user_set.add(user_id)
                users.append(user)

            identifications.append(new_identificaion)

        return identifications, users


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
        logger.info(f"Querying observations for {len(taxa_df)} taxa.")

        date_taxa_map = ObservationQuery.create_date_taxon_map(taxa_df)

        observations = []
        identifications = []
        users = []
        users_set = set()

        for date, ids in date_taxa_map.items():
            batches = ObservationQuery.get_batches(list(ids), self.batch_size)
            logger.debug("")
            if date != "None":
                logger.debug(f"*** Processing taxa with 'created after' date filter: {date} ***")
                base_params['created_d1'] = date
            else:
                logger.debug("*** Processing taxa with no 'created after' date filter ***")
            
            for i, batch in enumerate(batches, start=1):
                logger.debug("")
                logger.debug(f"Processing batch #{i} with {len(batch)} taxa...")
                # Get list of JSON response dictionaries
                results = ObservationQuery.download_observations(batch, base_params, headers)
                # Add observations, identification, and users from results
                for result in results:
                    new_obs, new_ident, new_users = self.add_records_from_result(
                        result,
                        users_set
                    )
                    observations.append(new_obs)
                    identifications.extend(new_ident)
                    users.extend(new_users)
        
        observations_df = pd.DataFrame(observations)
        identifications_df = pd.DataFrame(identifications)
        users_df = pd.DataFrame(users)

        observations_df.to_csv("output/observations.csv", index=False)
        identifications_df.to_csv("output/identifications.csv", index=False)
        users_df.to_csv("output/users.csv", index=False)

        print(f"Observations:\n{observations_df.head(50)}\n")
        print(f"Identifications:\n{identifications_df}\n")
        print(f"Users:\n{users_df}\n")

        return observations, identifications, users
        

class ProjectMembers:
    def __init__(self, config: ConfigParser):
        self.project_id = config["observations"]["project_id"]
        self.per_page = config["observations"]["per_page"]
    

    def fetch_project_members(self, auth: iNaturalistAuth):
        url = f"https://api.inaturalist.org/v2/projects/{self.project_id}/members"
        headers = auth.get_auth_headers()
        params = {
            "per_page": self.per_page
        }

        # Make API requests
        all_results = []
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
                all_results.extend(results)
                time.sleep(0.5)

                if len(results) < self.per_page:
                    break

                page += 1
                time.sleep(0.5)
                
            except requests.Timeout:
                logger.error(f"Request for taxon {params["taxon_id"]} timed out.")
        
        # Extract user IDs from API response
        users = set()
        for result in all_results:
            user_id = result.get("user", {}).get("id")
            users.add(user_id)
            