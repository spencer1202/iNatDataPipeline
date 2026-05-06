#!/usr/bin/env python3
"""
iNaturalist Taxon ID Cache Builder with Name Mapping

This script builds a CSV file mapping scientific names to taxon_ids 
for efficient batch querying of iNaturalist observations. It also tracks
how tracking list names map to iNaturalist names, handling cases where
names differ due to taxonomic updates, synonyms, or spelling differences.
If you need to manually override any of the taxon name matches, record
those changes in the CSV file referred to in the config file as 
name_overrides_file.

Usage:
    python pipeline/taxa.py

Output:
    - 'mappings_[date].csv': Complete mapping table with columns:
      * inat_name: Corresponding name found in iNaturalist (may be different)
      * taxon_id: iNaturalist taxon ID (blank if no match found)
      * last_updated: The date that this mapping was last updated
      * generic_name: If this is populated, this taxon is a undescribed and the 
      taxon ID refers to the next lowest taxonomic classification
"""
import requests
import datetime
import pandas as pd
import configparser
import logging
import os
import re
import time
import numpy as np
from typing import Dict, Optional, Tuple

import helpers

log_folder = "logs"
log_file = "taxon_cache_builder.log"
logger = logging.getLogger(__name__)

# Helper Functions
#########################################################################################

def load_tracking_list(file) -> pd.DataFrame:
    """
    Loads tracking list dataframe from the provided file, renames and filters for the relevant columns, 
    and returns the result.

    The resulting dataframe has the columns sname, scomname, and elcode.

    Args:
        file:
            Name of file to load tracking dataframe from. Should be a CSV with SNAME, ELCODE, and SCOMNAME 
            as columns.
    
    Returns:
        Loaded and cleaned dataframe.
    """

    df = pd.read_csv(file, encoding="latin1")
    df = df.rename(columns={"SNAME": "sname", "ELCODE": "elcode", "SCOMNAME": "scomname"})
    return df[["sname", "scomname", "elcode"]]


def load_mapping_list(map_file: str = None):
    """
    Creates dataframe from existing name mapping file if it exists.

    Args:
        map_file:
            Name of the file with the existing taxon name mappings, or None to force rebuild.
    
    Returns:
        A name mappings dataframe if map_file is not None and the file exists. Otherwise returns an
        empty dataframe with the required columns.

    """
    cols = [
        "sname",
        "elcode",
        "taxon_id",
        "inat_name",
        "last_updated",
        "sname_clean"
    ]

    if map_file and os.path.exists(map_file):
        return pd.read_csv(map_file, encoding="latin1")
    else:
        return pd.DataFrame(columns=cols)
    

def setup_dfs(tracking_file: str, mapping_file: str, overrides_file: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Takes care of all the loading, error handling, and setup for all three required dataframes.

    Args:
        tracking_file:
            File path of species tracking list csv
        mapping_file:
            File path of existing taxon name mapping file, or None to force rebuild
        overrides_file:
            File path of name overrides file
    
    Returns:
        Three dataframes: (1) The cleaned tracking list dataframe, (2) a dataframe with the existing
        mappings, or an empty mapping dataframe, and (3) the name overrides dataframe
    """
    # Load tracking list
    try:
        tracking_df = load_tracking_list(tracking_file)
        logger.info(f"Loaded tracking list with {len(tracking_df)} entries")
    except FileNotFoundError as ex:
        logger.error(f"Could not find tracking list file: {tracking_file}.")
        raise
    except KeyError as ex:
        logger.error(f"File \"{tracking_file}\" does not have required columns (SNAME, ELCODE, and SCOMNAME)")
        raise
    except:
        logger.error(f"Encountered unknown error while loading tracking list: {tracking_file}")
        raise

    # Load existing mappings
    try:
        mapping_df = load_mapping_list(mapping_file)
    except:
        to_rebuild = helpers.get_yn_input("Failed to load existing mappings. Rebuild from scratch? (Y/N): ")
        if to_rebuild:
            mapping_df = load_mapping_list()
        else:
            logger.info(f"Exiting program.")
            raise Exception()

    if len(mapping_df) == 0:
        logger.info(f"Bulding taxon mapping from scratch.")
    else:
        logger.info(f"Loaded existing mappings with {len(mapping_df)} entries")

    # Load name overrides
    try:
        overrides_df: pd.DataFrame = pd.read_csv(
            overrides_file, usecols=["sname", "elcode", "scomname", "inat_name"]
        )
    except FileNotFoundError:
        logger.error(f"Could not find overrides file: {overrides_file}")
        raise
    except ValueError:
        logger.error(f"Overrides file \"{overrides_file}\" does not have the required columns.")
        raise

    return tracking_df, mapping_df, overrides_df


def get_to_match_list(tracking_df: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
    """
    Get a copy of the tracking dataframe with only records that are not already present
    in the mapping dataframe.

    Args:
        tracking_df:
            Tracking list dataframe
        
        mapping_df:
            Taxon name mapping dataframe.
    
    Returns:
        A filtered copy of the tracking dataframe.
    """
    match_mask = tracking_df["elcode"].isin(mapping_df["elcode"])
    return tracking_df[~match_mask].copy()



def get_name_overrides(df: pd.DataFrame, overrides_df: pd.DataFrame) -> pd.Series | None:
    """
    Returns a column for df populated with name overrides from 
    overrides_df.

    Args:
        df: 
            The dataframe to select name overrides for
        overrides_df: 
            A dataframe with name overrides. Should have the columns: sname, elcode, scomname, 
            and inat_name.
    
    Returns:
        A series populated with any name overrides for df, or None if there are no name overrides.
    """
    return df["elcode"].map(overrides_df.set_index("elcode")["inat_name"])


def preprocess_name(name: str) -> str:
    """
    Preprocess taxon name for iNaturalist API query by converting trinomial format
    
    Converts names like "Aster alpinus var. vierhapperi" to "Aster alpinus vierhapperi"
    which is the preferred format for iNaturalist queries.
    
    Args:
        name: Scientific name to preprocess
        
    Returns:
        Name with "var.", "pop.", and "ssp." removed for better iNaturalist matching
    """
    if not name or pd.isna(name):
        return None
    
    # Regular expression that extracts the genus name, species name, and subspecies name or 
    # subspecies/population number.
    expr = r"^((?:[a-zA-Z\-]+[ \t]){1,2})(?:(?:var\.|pop\.|ssp\.)\s)?(.+)?"
    match = re.search(expr, name.strip())
    if not match:       # some weird edge case
        return None
    
    processed_name = match.group(1) + match.group(2)

    # Clean up any double spaces
    while "  " in processed_name:
        processed_name = processed_name.replace("  ", " ")
    
    return processed_name.strip()


def get_undescribed_names(df: pd.DataFrame) -> pd.Series:
    """
    Identifies all undescribed scientific names, meaning they have a number instead of a species/subspecies 
    or a population number, and populates a Series with the more generic names.

    Args:
        df: The dataframe to identify undescribed taxa
    
    Returns:
        A series populated with the higher taxonomic classification if a taxa is undescribed.
    """
    # Matches names with a number at the end, grabs all text before the number
    expr = r"^((?:[A-Za-z\-]+[\t ])+[A-Za-z\-]+)[\t ]\d+$"
    return df["sname_clean"].str.extract(expr)


def clean_taxon_id(id: str) -> int | None:
    """
    Extracts a valid integer taxon ID from the provided string.

    Args:
        id:
            Taxon ID string from iNaturalist.
    
    Returns:
        Integer value of taxon ID, or None if provided string is not a valid taxon ID.
    """
    if id and not pd.isna(id) and str(id).lower() != "nan":
        try:
            clean_id = int(float(id))
            return clean_id
        except (ValueError, TypeError):
            return None
    else:
        return None


# Taxon Cache Builder Class
#########################################################################################

class TaxonCacheBuilder:

    def __init__(self, config_file = "config.ini"):
        """Initialize with configuration file"""
        self.config_file = config_file
        self.config = helpers.load_config(config_file)
        self.access_token = None
        
    
    def setup_access(self):
        """Set up access token to be used when querying taxon names"""
        self.access_token = helpers.get_access_token(self.config["authentication"]["username"])
        

    def query_taxon(self, scientific_name: str) -> Tuple[Optional[int], Optional[str]]:
        """
        Get taxon_id and matched name for a scientific name using iNaturalist API
        
        Args:
            scientific_name: The scientific name to look up
            
        Returns:
            Tuple of (taxon_id, matched_name) if found, (None, None) otherwise
        """

        url = "https://api.inaturalist.org/v1/taxa"
        if not self.access_token:
            self.setup_access()
        headers = helpers.get_auth_headers(self.access_token, self.config["authentication"]["user_agent"])

        params = {
            "q"         : scientific_name,
            "per_page"  : 5,
            "order"     : "desc",
            "order_by"  : "observations_count"
        }

        # Make API request
        try:
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return (None, None)
        
        except requests.RequestException as e:
            logger.error(f"Error looking up '{scientific_name}': {e}")
            return None, None

        # Look for exact name match first
        for result in results:
            result_name = result.get("name", "")
            result_id = result.get("id")
            
            # Handle NaN values and ensure we have valid data
            if pd.isna(result_name) or pd.isna(result_id) or not result_name or not result_id:
                continue
            if type(result_name) != str:
                continue

            if result_name.lower() == scientific_name.lower(): #exact match
                return int(result_id), result_name

        # If no exact match, take first valid result (most observations)
        for result in results:
            result_name = result.get("name", "")
            result_id = result.get("id")
            
            # Handle NaN values and ensure we have valid data
            if pd.isna(result_name) or pd.isna(result_id) or not result_name or not result_id:
                continue
            return int(result_id), result_name
    
        return (None, None)


    def export(self, df, out_file):
        """
        Export the dataframe and update the config file with the latest cache filepath
        """
        df.to_csv(out_file, index=False)
        self.config.set("taxon_map", "map_file", out_file)
        with open(self.config_file, 'w') as fp:
            self.config.write(fp)


    
    def build_cache(self, force_rebuild: bool = False) -> Dict[str, int]:
        """
        Build taxon_id cache from tracking list and save name mappings to CSV
        """
        # Get config settings
        overrides_file: str     = self.config["taxon_map"]["name_overrides_file"]
        tracking_list_file: str = self.config["taxon_map"]["tracking_list"]
        map_file: str           = self.config["taxon_map"]["map_file"] if not force_rebuild else None

        # Set up output file in name_maps folder
        name_map_folder: str = "taxonomy/name_maps"
        os.makedirs(name_map_folder, exist_ok=True)
        out_mapping_file = os.path.join(name_map_folder, "mappings_" + datetime.datetime.now().strftime("%Y%m%d") + ".csv")
        
        # Get timestamp
        today = datetime.date.today()

        # Load and error check all DFs
        tracking_df, mapping_df, overrides_df = setup_dfs(
            tracking_list_file, map_file, overrides_file
        )
        
        #################### Preprocessing ####################
        # Get records that need to be matched
        to_match = get_to_match_list(tracking_df, mapping_df)
        if len(to_match) == 0:
            logger.info("All taxa on tracking list are already in current taxon map.")
            self.export(mapping_df, out_mapping_file)
            return
        logger.info(f"Found {len(to_match)} tracking list entries not present in existing mappings.")

        # Insert name overrides
        to_match["sname_clean"] = get_name_overrides(to_match, overrides_df)
        overrides_count = len(to_match[to_match["sname_clean"].notna()])
        logger.info(f"Processing overrides: found {overrides_count} name(s) in tracking list with name overrides.")
            
        # Preprocess tracking list
        to_match["sname_clean"] = np.where(
            to_match["sname_clean"].isna(), 
            to_match["sname"].apply(preprocess_name), 
            to_match["sname_clean"]
        )

        # Process undescribed species
        to_match["generic_name"] = get_undescribed_names(to_match)
    
        # Process unmatched rows
        process_total = len(to_match)
        process_num = 1
        new_rows = []
        undescribed_names: dict[tuple[int, str]] = {}

        #################### Querying ####################
        logger.info("Beginning taxon queries...")
        for _, row in to_match.iterrows():
            sname = row["sname_clean"]
            generic_name = row["generic_name"]
            logger.info(f"{process_num:>4} / {process_total}\t{sname}")

            # Check if this is an undescribed taxon, and if so if it has already been mapped.
            if pd.isna(generic_name):
                taxon_id, matched_name = self.query_taxon(sname)
            else:
                if not undescribed_names.get(generic_name):
                    taxon_id, matched_name = self.query_taxon(generic_name)
                    undescribed_names[generic_name] = (taxon_id, matched_name)
                else:
                    taxon_id, matched_name = undescribed_names.get(generic_name)

            clean_id = clean_taxon_id(taxon_id)
            
            # Copy all existing fields from tracking_df
            new_row = row.to_dict()
            # Add / overwrite mapping fields
            new_row["taxon_id"] = clean_id
            new_row["inat_name"] = matched_name
            new_row["last_updated"] = today

            new_rows.append(new_row)
            process_num += 1
            # Be kind to the API
            time.sleep(1)

        if new_rows:
            mapping_df = pd.concat([mapping_df, pd.DataFrame(new_rows)], ignore_index=True)
            mapping_df = mapping_df.drop(columns=["sname_clean"])
            mapping_df = mapping_df.drop_duplicates(subset="sname", keep="last")
        
        self.export(mapping_df, out_mapping_file)
        

def logging_setup():
# Make sure name maps folder exists
    os.makedirs(log_folder, exist_ok=True)

    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    file_handler = logging.FileHandler(os.path.join(log_folder, log_file))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M"))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def main():
    logging_setup()

    logger.info("*** Running TaxonCacheBuilder ***")
    logger.info("---------------------------------")

    builder = TaxonCacheBuilder()
    builder.setup_access()
    builder.build_cache(force_rebuild=True)

    logger.info("Done!")
    logger.info("----------------------------------\n")



if __name__ == "__main__":
    main()