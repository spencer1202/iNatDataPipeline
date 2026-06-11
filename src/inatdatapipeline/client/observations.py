"""
observations.py

This module defines the ObservationQuery class, which uses the iNaturalist API to download 
observations and their corresponding identifications then structures the results.
"""
#### Standard imports ####
import datetime as dt
import logging
import json
from typing import Optional
from dataclasses import dataclass, field

#### Third-party imports ####
import pandas as pd
import prison

#### Local imports ####
from inatdatapipeline.client import helpers
from inatdatapipeline.schemas.config import ObservationsConfig
from inatdatapipeline.client.authentication import (
    INaturalistAuth
)

#### Setup ####
logger = logging.getLogger('pipeline')


# ---------------------------------------------------------------------------
# ObservationResults
# ---------------------------------------------------------------------------
@dataclass
class ObservationResults():
    """
    Structured results of the iNaturalist observation requests.
    * **observations**: DataFrame of iNaturalist observations.
    * **identifications**: DataFrame of identifications for the returned observations.
    * **users**: DataFrame of users, both observers and identifiers.
    * **annotations**: All of the annotations left on the observations.
    * **completed_taxa**: Set of taxon IDs for which all observations have been recieved.
    """
    observations    : list[dict]    = field(default_factory=list)
    identifications : list[dict]    = field(default_factory=list)
    users           : list[dict]    = field(default_factory=list)
    annotations     : list[dict]    = field(default_factory=list)
    completed_taxa  : set           = field(default_factory=set)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _get_batches(full_list: list, batch_size: int):
    """Helper function to yield successive n-sized chunks from list"""
    for i in range(0, len(full_list), batch_size):
        yield full_list[i:i + batch_size]


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

    return helpers.sliding_page_requests(url, params, headers)


def _apply_date_filter(df: pd.DataFrame, update_days: int | None) -> pd.DataFrame:
    """
    Filters the dataframe for taxa that were last updated more than update_days ago. If
    update_days is zero or None, set all taxas' date_updated column to None.
    """
    df = df.copy()
    # If days_updated is zero, update all taxa without a date filter.
    if not update_days:
        df["date_updated"] = None

    # Filter for taxa queried more than days_updated before now
    else:
        target_date = dt.date.today() - dt.timedelta(days=update_days)
        date_mask = pd.to_datetime(df["date_updated"]) <= pd.Timestamp(target_date)
        df = df[(df["date_updated"].isna()) | date_mask]

    return df


def _get_fields_rison(file_path: str) -> str:
    """
    Helper function that reads the contents of the provided JSON file and returns a RISON
    encoded string.
    """
    try:
        with open(file_path, "r", encoding="latin-1") as fp:
            fields_dict = json.load(fp)
    except FileNotFoundError as ex:
        raise ValueError(f"Fields JSON file not found: {file_path}") from ex
    except json.JSONDecodeError as ex:
        raise ValueError(f"Failed to parse fields JSON file: {file_path}") from ex

    return prison.dumps(fields_dict)


def _unpack_observation(data) -> list[dict]:
    """
    Structure an iNaturalist observation JSON response into a list of dictionaries.
    """
    long = data.get("geojson", {}).get("coordinates", [None, None])[0] # geojson has long first
    lat = data.get("geojson", {}).get("coordinates", [None, None])[1]

    private_geojson = data.get("private_geojson")
    long_private = (
        private_geojson.get("coordinates", [None, None])[0]
        if private_geojson
        else None
    )
    lat_private = (
        private_geojson.get("coordinates", [None, None])[1]
        if private_geojson
        else None
    )

    observation = {
        "observation_id"                : data.get("id"),
        "uuid"                          : data.get("uuid"),
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
        "has_photo"                     : len(data.get("photos", [])) > 0,
        "has_recording"                 : len(data.get("sounds", [])) > 0
    }
    return observation


def _unpack_identifications(
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
            # "current"           : identification.get("current"),
            "taxon_id"          : identification.get("taxon", {}).get("id")
        }
        if user_id and user_id not in user_set:
            user_set.add(user_id)
            users.append(user)
        identifications.append(new_identificaion)

    return identifications, users


def _unpack_annotations(observation_id: int, annotation_list: list) -> Optional[list[dict]]:
    """
    Extracts dictionaries of annotations from an observation's annotation list.
    """
    if annotation_list is None or len(annotation_list) == 0:
        return None

    annotations = []
    for annotation in annotation_list:
        new_annotation = {
            "observation_id"    : observation_id,
            "annotation_id"     : annotation.get("controlled_attribute_id"),
            "value_id"          : annotation.get("controlled_value_id"),
            "user_id"           : annotation.get("user_id"),
            "vote_score"        : annotation.get("vote_score")
        }
        annotations.append(new_annotation)

    return annotations


def _unpack_results(data: list, all_observations: ObservationResults, users_set: set):
    """
    Extract observations, identifications, and users from a list of nested dictionaries
    into the ObservationsResult object. Mutates all_observations and returns the updated 
    users_set.
    """
    users_set = users_set.copy()
    for result in data:
        # Add new observation
        observation = _unpack_observation(result)
        all_observations.observations.append(observation)

        # Add annotations
        annotations = _unpack_annotations(
            observation.get("observation_id"),
            result.get("annotations")
        )
        if annotations is not None:
            all_observations.annotations.extend(annotations)

        # Get user who made the observation, add to users set if not already present
        obs_user = result.get("user", {})
        if obs_user.get("id") and obs_user.get("id") not in users_set:
            users_set.add(obs_user.get("id"))
            all_observations.users.append(obs_user)

        # Add identifications
        identifications, new_users = _unpack_identifications(
            observation.get("observation_id"),
            result.get("identifications"),
            users_set
        )
        all_observations.users.extend(new_users)
        all_observations.identifications.extend(identifications)

    return users_set

# ---------------------------------------------------------------------------
# Fetch Observations
# ---------------------------------------------------------------------------
def fetch_observations(
        auth: INaturalistAuth,
        taxa_df: pd.DataFrame,
        config: ObservationsConfig
) -> Optional[ObservationResults]:
    """
    Downloads observations of taxa in taxa_df from iNaturalist and structures the results
    into observations, identifications, users, and the set of taxa searched for.
    Args:
        auth:
            iNaturalist authentication object with an active access token
        taxa_df:
            Dataframe of iNaturalist taxa to request.
    Returns:
        Dataframes with the recieved observations, identifications, and users respectively, and a 
        set of all taxa that were searched for. Returns None if there are no taxa left to search 
        for.
    """
    # Set up base parameters
    base_params = {
        'place_id'          : config.place_id,
        'quality_grade'     : config.quality_grade,
        'per_page'          : config.per_page,
        'order_by'          : 'id',
        'order'             : 'asc',
    }
    base_params["fields"] = _get_fields_rison(config.fields_json)
    if config.project_id:
        base_params["project_id"] = config.project_id

    # Set up taxa dataframe
    taxa_df = _apply_date_filter(taxa_df, config.update_after_days)
    if len(taxa_df) == 0:
        return None

    logger.info("Downloading observations for %i taxa.", len(taxa_df))

    # Create date taxa map
    date_taxa_map = _create_date_taxon_map(taxa_df)

    # Iterate through taxon IDs and run requests
    all_observations    = ObservationResults()
    users_set           = set()
    max_reached         = False

    for date, ids in date_taxa_map.items():
        batches = _get_batches(list(ids), config.batch_size)
        logger.debug("")
        if date != "None":
            logger.debug("Processing taxa with 'created after' date filter: %s", str(date))
            base_params['created_d1'] = date
        else:
            logger.debug("Processing taxa with no 'created after' date filter")

        for i, batch in enumerate(batches, start=1):
            logger.debug("* Processing batch #%i with %i taxa...", i, len(batch))
            data = _request_batch(
                batch, base_params, auth.get_auth_headers()
            )
            logger.debug("  Finished downloading %i results.", len(data))

            # Unpack results into all_observations
            users_set = _unpack_results(data, all_observations, users_set)

            # Update set of completed taxa
            all_observations.completed_taxa.update(batch)

            if len(all_observations.observations) > config.max_observations:
                logger.info("Exceeded maximum number of observations for this run. " +
                            "Wrapping up queries...")
                max_reached = True
                break

        if max_reached:
            break

    return all_observations
