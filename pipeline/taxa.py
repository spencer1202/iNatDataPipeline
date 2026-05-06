#!/usr/bin/env python3
"""
iNaturalist Taxon ID Cache Builder with Name Mapping

This script builds a dictionary mapping scientific names to taxon_ids 
for efficient batch querying of iNaturalist observations. It also tracks
how tracking list names map to iNaturalist names, handling cases where
names differ due to taxonomic updates, synonyms, or spelling differences.
If you need to manually override any of the taxon name matches, record
those changes in the CSV file referred to in the config file as 
name_overrides_file.

Usage:
    python build_taxon_cache.py

Output:
    - 'taxon_name_mappings.csv': Complete mapping table with columns:
      * iNat_name: Corresponding name found in iNaturalist (may be different)
      * taxon_id: iNaturalist taxon ID (blank if no match found)
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

logfile = "logs/taxon_cache_builder.log"
logger = logging.getLogger(__name__)
        

class TaxonCacheBuilder:

    def __init__(self, config_file = "config.ini"):
        """Initialize with configuration file"""
        self.config_file = config_file
        self.config = helpers.load_config(config_file)
        self.access_token = None

    
    @staticmethod
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
        
        # Regular expression that extracts just the genus name, species name, and subspecies name or 
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
        
    
    def setup_access(self):
        """Set up access token to be used when querying taxon names"""
        self.access_token = helpers.get_access_token(self.config["authentication"]["username"])
        

    def get_taxon_info(self, scientific_name: str) -> Tuple[Optional[int], Optional[str]]:
        """
        Get taxon_id and matched name for a scientific name using iNaturalist API
        
        Args:
            scientific_name: The scientific name to look up
            
        Returns:
            Tuple of (taxon_id, matched_name) if found, (None, None) otherwise
        """
        # Preprocess the name for better iNaturalist matching
        processed_name = self.preprocess_name(scientific_name)

        url = "https://api.inaturalist.org/v1/taxa"
        if not self.access_token:
            self.setup_access()
        headers = helpers.get_auth_headers(self.access_token, self.config["authentication"]["user_agent"])

        params = {
            "q"         : processed_name,
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
    
    
    @staticmethod
    def insert_overrides(df: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
        match_mask = df["elcode"].isin(overrides["elcode"])
        df["sname_clean"] = df["elcode"].map(overrides.set_index("elcode")["inat_name"])


    @staticmethod
    def process_undescribed(df: pd.DataFrame) -> pd.DataFrame:
        """
        Identifies all undescribed scientific names, meaning they have a number instead of a species/subspecies or 
        a population number, and populates a new column with their more generic name.

        Args:
            df: The dataframe to identify undescribed taxa
        
        Returns:
            The dataframe with a new "generic_name" column added that is populated with a higher taxonomic 
            classification if the taxa is undescribed.
        """
        # Matches names with a number at the end, grabs all text before the number
        expr = r"^((?:[A-Za-z\-]+[\t ])+[A-Za-z\-]+)[\t ]\d+$"
        df["generic_name"] = df["sname_clean"].str.extract(expr)
        
        return df

    @staticmethod
    def clean_taxon_id(id: str) -> int | None:
        # Clean up taxon ID
        if id and not pd.isna(id) and str(id).lower() != "nan":
            try:
                clean_taxon_id = int(float(id))
                return clean_taxon_id
            except (ValueError, TypeError):
                return None
        else:
            return None
    

    def export(self, df, out_file):
        """
        Export dataframe to file and update the latest cache filepath in the config file
        """
        df.to_csv(out_file, index=False)
        self.config.set("taxon_map", "map_file", out_file)
        with open(self.config_file, 'w') as fp:
            self.config.write(fp)

    
    def build_cache(self, force_rebuild: bool = False) -> Dict[str, int]:
        """
        Build taxon_id cache from tracking list and save name mappings to CSV

        Returns:
            Dictionary mapping scientific names to taxon_ids
        """
        # Get config settings
        tracking_list_file: str = self.config["taxon_map"]["tracking_list"]
        overrides_file: str     = self.config["taxon_map"]["name_overrides_file"]
        map_file: str           = self.config["taxon_map"]["map_file"]

        # Make sure name maps folder exists
        name_map_folder: str = "taxonomy/name_maps"
        os.makedirs(name_map_folder, exist_ok=True)

        out_mapping_file = os.path.join(name_map_folder, "mappings_" + datetime.datetime.now().strftime("%Y%m%d") + ".csv")
        
        cols = [
            "sname",
            "elcode",
            "taxon_id",
            "inat_name",
            "last_updated",
            "sname_clean"
        ]

        today = datetime.date.today()

        # Load tracking list
        tracking_df = pd.read_csv(tracking_list_file, encoding="latin1")
        tracking_df = tracking_df.rename(columns={"SNAME": "sname", "ELCODE": "elcode", "SCOMNAME": "scomname"})
        tracking_df = tracking_df[["sname", "scomname", "elcode"]]
        logger.info(f"Loaded tracking list with {len(tracking_df)} entries")

        # Load existing map file
        if os.path.exists(map_file) and not force_rebuild:
            try:
                mappings_df = pd.read_csv(map_file)
                logger.info(f"Loaded existing mappings with {len(mappings_df)} entries")
            except:
                if helpers.get_yn_input("Failed to load existing mappings. Rebuild from scratch? (Y/N): "):
                    logger.info(f"Rebuilding whole taxon mapping.")
                    mappings_df = pd.DataFrame(columns=cols)
                else:
                    logger.info(f"Exiting program.")
                    return None
        else:
            logger.info(f"Rebuilding whole taxon mapping.")
            mappings_df = pd.DataFrame(columns=cols)

        # Filter for names that still need to be processed
        to_match: pd.DataFrame = tracking_df[~tracking_df["elcode"].isin(mappings_df["elcode"])].copy()
        if len(to_match) == 0:
            logger.info("All taxa on species list are already in current taxon map.")
            self.export(mappings_df, out_mapping_file)
            return
        
        logger.info(f"Found {len(to_match)} tracking list entries not present in existing mappings.")

        # Insert name overrides
        overrides_df: pd.DataFrame = pd.read_csv(overrides_file)
        if len(overrides_df):
            logger.info(f"Replaces {len(overrides_df)} names with names from overrides file...")
            self.insert_overrides(to_match, overrides_df)
            
        # Preprocess tracking list
        to_match["sname_clean"] = np.where(to_match["sname_clean"].isna(), to_match["sname"].apply(self.preprocess_name), to_match["sname_clean"])

        # Process undescribed species
        to_match = TaxonCacheBuilder.process_undescribed(to_match)
    
        # Process unmatched rows
        process_total = len(to_match)
        process_num = 1
        new_rows = []
        undescribed_names: dict[tuple[int, str]] = {}

        for _, row in to_match.iterrows():
            sname = row["sname_clean"]
            generic_name = row["generic_name"]
            logger.info(f"[Processing {process_num} / {process_total}]\t{sname}")

            # Check if this is an undescribed taxon, and if so if it has already been mapped.
            if pd.isna(generic_name):
                taxon_id, matched_name = self.get_taxon_info(sname)
            else:
                if not undescribed_names.get(generic_name):
                    taxon_id, matched_name = self.get_taxon_info(generic_name)
                    undescribed_names[generic_name] = (taxon_id, matched_name)
                else:
                    taxon_id, matched_name = undescribed_names.get(generic_name)

            clean_taxon_id = TaxonCacheBuilder.clean_taxon_id(taxon_id)
            
            # Copy all existing fields from tracking_df
            new_row = row.to_dict()
            # Add / overwrite mapping fields
            new_row["taxon_id"] = clean_taxon_id
            new_row["inat_name"] = matched_name
            new_row["last_updated"] = today

            new_rows.append(new_row)
            process_num += 1
            # Be kind to the API
            time.sleep(1)

        if new_rows:
            mappings_df = pd.concat([mappings_df, pd.DataFrame(new_rows)], ignore_index=True)
            mappings_df = mappings_df.drop(columns=["sname_clean"])
            mappings_df = mappings_df.drop_duplicates(subset="sname", keep="last")
        
        self.export(mappings_df, out_mapping_file)
        


def main():
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    file_handler = logging.FileHandler(logfile)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M"))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    logger.info("*** Running TaxonCacheBuilder ***")
    logger.info("---------------------------------")

    builder = TaxonCacheBuilder()
    builder.setup_access()
    builder.build_cache(force_rebuild=False)

    logger.info("Done!")
    logger.info("----------------------------------\n")



if __name__ == "__main__":
    main()