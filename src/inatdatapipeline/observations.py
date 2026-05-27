"""
observations.py

This module defines the ObservationQuery class, which uses the iNaturalist API to download 
observations and their corresponding identifications then structures the results.
"""
import pandas as pd
import datetime as dt
import logging
import prison
import json
import numpy as np
from typing import NamedTuple

from inatdatapipeline import config
from inatdatapipeline.request_helpers import INaturalistAuth, PageRequests, SlidingPageRequests
from inatdatapipeline.db_manager import DBManager

logger = logging.getLogger('pipeline')

class ObservationsResult(NamedTuple):
    """
    Structured results of the iNaturalist observation requests.
    * **observations**: DataFrame of iNaturalist observations.
    * **identifications**: DataFrame of identifications for the returned observations.
    * **users**: DataFrame of users, both observers and identifiers.
    * **completed_taxa**: Set of taxon IDs for which all observations have been recieved.
    """
    observations    : list[dict] = list()
    identifications : list[dict] = list()
    users           : list[dict] = list()
    completed_taxa  : set = set()


class ObservationQuery:
    """
    This class handles requesting observations from iNaturalist and organizing them into 
    observations, identifications, and users.
    """

    def __init__(self, cfg: config.ObservationsConfig):
        """
        Create object for pulling observations from iNaturalist API.
        Args:
            db_manager:
                Database manager object for accessing the local database
            config:
                ObservationsConfig object with configuration options.
        """
        self.config = cfg

    @staticmethod
    def _get_batches(full_list: list, batch_size: int):
        """Helper function to yield successive n-sized chunks from list"""
        for i in range(0, len(full_list), batch_size):
            yield full_list[i:i + batch_size]


    @staticmethod
    def _create_date_taxon_map(taxa_df: pd.DataFrame) -> dict[str: set]:
        """
        Creates a map that groups taxon_ids into sets with date_updated as the key.
        Args:
            taxa_df: 
                Taxa dataframe to create a date map from
        Returns:
            Dictionary that maps a date string to a set of taxon IDs.
        """
        date_taxon_map: dict = taxa_df.groupby("date_updated")["taxon_id"].apply(set).to_dict()
        date_taxon_map["None"] = set(taxa_df[taxa_df["date_updated"].isna()]["taxon_id"])
        return date_taxon_map


    @staticmethod
    def _request_batch(ids: list, params: dict, headers: str) -> list:
        """
        Download iNaturalist observations for a list of ID.
        Args:
            ids:
                List of taxon IDs to download observations for.
            params:
                Base HTTP request parameters.
            headers:
                HTTP authentication headers.
        Returns:
            A list of result dictionaries, decoded from the HTTP response.
        """
        params["taxon_id"] = ",".join(str(id) for id in ids)
        url = "https://api.inaturalist.org/v2/observations"

        return SlidingPageRequests(url, params, headers, params["per_page"])


    @staticmethod
    def _apply_date_filter(df: pd.DataFrame, update_days: int | None) -> pd.DataFrame:
        """
        Filters the dataframe for taxa that were last updated more than update_days ago. If
        update_days is zero or None, set all taxas' date_updated column to None.
        """
        # If days_updated is zero, update all taxa without a date filter.
        if not update_days:
            df["date_updated"] = None

        # Filter for taxa queried more than days_updated before now
        else:
            target_date = dt.date.today() - dt.timedelta(days=update_days)
            date_mask = pd.to_datetime(df["date_updated"]) <= pd.Timestamp(target_date)
            df = df[(df["date_updated"].isna()) | date_mask]

        return df
    
    
    @staticmethod
    def get_fields_rison(file_path: str) -> str:
        """
        Helper function that reads the contents of the provided JSON file and returns a RISON
        encoded string.
        """
        try:
            with open(file_path, "r", encoding="latin-1") as fp:
                fields_dict = json.load(fp)
            return prison.dumps(fields_dict)
        except:
            raise ValueError(f"Failed to load query observation fields from file: " +
                         "{self.config.fields_json}.")


    def unpack_observation(self, data) -> list[dict]:
        lat = data.get("geojson", {}).get("coordinates", [None, None])[0]
        long = data.get("geojson", {}).get("coordinates", [None, None])[1]
        lat_private = data.get("private_geojson", {}).get("coordinates", [None, None])[0]
        long_private = data.get("private_geojson", {}).get("coordinates", [None, None])[1]
        in_project = self.config.project_id in data.get("project_ids", [])

        observation = {
            "observation_id"                : data.get("id"),
            "observer_id"                   : data.get("user", {}).get("id"),
            "taxon_id"                      : data.get("community_taxon_id"),
            "license"                       : data.get("license_code"),
            "latitude"                      : lat,
            "longitude"                     : long,
            "latitude_private"              : lat_private,
            "longitude_private"             : long_private,
            "coordinate_precision"          : data.get("positional_accuracy"),
            "coordinate_precision_public"   : data.get("public_positional_accuracy"),
            "observed_on"                   : data.get("observed_on"),
            "observed_on_string"            : data.get("observed_on_string"),
            "created_at"                    : data.get("created_at"),
            "updated_at"                    : data.get("updated_at"),
            "quality_grade"                 : data.get("quality_grade"),
            "url"                           : data.get("uri"),
            "description"                   : data.get("description"),
            "id_agreements"                 : data.get("num_identification_agreements"),
            "id_disagreements"              : data.get("num_identification_disagreements"),
            "captive_cultivated"            : data.get("captive"),
            "place_guess"                   : data.get("place_guess"),
            "place_guess_private"           : data.get("place_guess_private"),
            "obscured"                      : data.get("obscured"),
            "in_project"                    : in_project
        }
        return observation
    

    
    @staticmethod
    def unpack_identifications(
        observation_id: int,
        ident_list: list,
        user_set: set
    ) -> tuple[list, list]:
        """
        Extracts dictionaries of identifications and new users from an observation's 
        identification list.

        Args:
            observation_id:
                The id of this observation, which will be added to the identification record as a 
                foreign key.
            ident_list:
                List of identification objects from the JSON response for this observation
            user_set:
                Set of user IDs that have already been encountered.
        Returns:
            (identifications, users):
                A tuple of two lists: a list of dictionaries with identifications for this 
                observation, and a list of dictionaries with the users who made the 
                identifications (only including users not yet in the user_set).
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


    def unpack_results(self, data: list, all_observations: ObservationsResult, users_set: set):
        for result in data:
            # Add new observation
            observation = self.unpack_observation(result)
            all_observations.observations.append(observation)

            # Get user who made the observation, add to users set if not already present
            obs_user = result.get("user", {})
            if obs_user.get("id") and obs_user.get("id") not in users_set:
                users_set.add(obs_user.get("id"))
                all_observations.users.append(obs_user)

            # Add identifications
            identifications, new_users = self.unpack_identifications(
                observation.get("observation_id"),
                result.get("identifications"),
                users_set
            )
            all_observations.users.extend(new_users)
            all_observations.identifications.extend(identifications)


    def fetch_observations(self, auth: INaturalistAuth, taxa_df: pd.DataFrame):
        """
        Downloads observations of taxa in taxa_df from iNaturalist and structures the results
        into observations, identifications, users, and the set of taxa searched for.
        Args:
            auth:
                iNaturalist authentication object with an active access token
            taxa_df:
                Dataframe of iNaturalist taxa to request.
        Returns:
            (observations, identifications, users,  searched_taxa_set):
                Dataframes with the recieved observations, identifications, and users 
                respectively, and a set of all taxa that were searched for.
        """
        # Set up base parameters
        base_params = {
            'place_id'          : self.config.place_id,
            'quality_grade'     : self.config.quality_grade,
            'per_page'          : self.config.per_page,
            'order_by'          : 'id',
            'order'             : 'asc',
        }
        base_params["fields"] = ObservationQuery.get_fields_rison(self.config.fields_json)
        
        # Set up taxa dataframe
        taxa_df = ObservationQuery._apply_date_filter(taxa_df, self.config.update_after_days)
        if len(taxa_df) == 0:
            raise ValueError("No taxa left to search for.")
        logger.info(f"Downloading observations for {len(taxa_df)} taxa.")

        # Create date taxa map
        date_taxa_map = ObservationQuery._create_date_taxon_map(taxa_df)

        # Iterate through taxon IDs and run requests
        all_observations    = ObservationsResult()
        users_set           = set()
        max_reached         = False

        for date, ids in date_taxa_map.items():
            batches = ObservationQuery._get_batches(list(ids), self.config.batch_size)
            logger.debug("")
            if date != "None":
                logger.debug(f"Processing taxa with 'created after' date filter: {date}")
                base_params['created_d1'] = date
            else:
                logger.debug("Processing taxa with no 'created after' date filter")

            for i, batch in enumerate(batches, start=1):
                logger.debug(f"* Processing batch #{i} with {len(batch)} taxa...")
                data = ObservationQuery._request_batch(
                    batch, base_params, auth.get_auth_headers()
                )
                logger.debug(f"  Finished downloading {len(data)} results.")

                # Unpack results into all_observations
                self.unpack_results(data, all_observations, users_set)

                # Update set of completed taxa
                all_observations.completed_taxa.update(batch)

                if len(all_observations.observations) > self.config.max_observations:
                    logger.info("Exceeded maximum number of observations for this run. " +
                                "Wrapping up queries...")
                    max_reached = True
                    break

            if max_reached:
                break

        return all_observations
