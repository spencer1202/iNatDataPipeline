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
import os
import time
import numpy as np
from typing import Dict, Optional, Tuple

import helpers


class TaxonCacheBuilder:

    def __init__(self, config_file = "config.ini"):
        """Initialize with configuration file"""
        self.config_file = config_file
        self.config = helpers.load_config(config_file)
        self.access_token = None
    

    def update_latest_cache(self, out_mapping_file):
        # Update most recent cache in config file
        self.config.set("taxon_map", "map_file", out_mapping_file)
        with open(self.config_file, 'w') as fp:
            self.config.write(fp)
    

    def preprocess_name(self, name: str) -> str:
        """
        Preprocess taxon name for iNaturalist API query by converting trinomial format
        
        Converts names like "Aster alpinus var. vierhapperi" to "Aster alpinus vierhapperi"
        which is the preferred format for iNaturalist queries.
        
        Args:
            name: Scientific name to preprocess
            
        Returns:
            Name with "var." and "ssp." removed for better iNaturalist matching
        """
        if not name or pd.isna(name):
            return None
        
        processed_name = str(name).strip()

        processed_name = processed_name.replace(" var. ", " ")
        processed_name = processed_name.replace(" ssp. ", " ")

        # Clean up any double spaces
        while "  " in processed_name:
            processed_name = processed_name.replace("  ", " ")
        
        return processed_name.strip()
    

    def setup_access(self):
        """Set up access token to be used when querying taxon names"""
        self.access_token = helpers.get_access_token()
        

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
            print(f"Error looking up '{scientific_name}': {e}")
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
    
    
    def build_cache(self) -> Dict[str, int]:
        """
        Build taxon_id cache from tracking list and save name mappings to CSV

        Returns:
            Dictionary mapping scientific names to taxon_ids
        """
        # Get config settings
        tracking_list_file: str = self.config["taxon_map"]["tracking_list"]
        overrides_file: str     = self.config["taxon_map"]["name_overrides_file"]
        map_file: str           = self.config["taxon_map"]["map_file"]
        force_rebuild: bool     = self.config["taxon_map"]["force_rebuild"]

        # Make sure name maps folder exists
        name_map_folder: str = "taxonomy/name_maps"
        os.makedirs(name_map_folder, exist_ok=True)

        out_mapping_file = os.path.join(name_map_folder, "mappings_" + datetime.datetime.now().strftime("%Y%m%d") + ".csv")
        
        cols = [
            "SNAME",
            "ELCODE",
            "taxon_id", 
            "iNat_name"
        ]

        # Load tracking list
        tracking_df = pd.read_csv(tracking_list_file, encoding="latin1", usecols=cols[:2])
        print(f"Loaded tracking list with {len(tracking_df)} entries")

        # Load existing map file
        if os.path.exists(map_file) and not force_rebuild:
            mappings_df = pd.read_csv(map_file, usecols=cols)
            print(f"Loaded existing mappings with {len(mappings_df)} entries")
        else:
            print(f"Rebuilding whole taxon mapping.")
            mappings_df = pd.DataFrame(columns=cols)
        
        # Load taxon overrides
        overrides_df: pd.DataFrame = pd.read_csv(overrides_file)

        # Filter for names that still need to be processed
        to_match = tracking_df[~tracking_df["ELCODE"].isin(mappings_df["ELCODE"])]
        print(f"Found {len(to_match)} tracking list entries not present in existing mappings.")
    
        # Process unmatched rows
        process_total = len(to_match)
        process_num = 1
        new_rows = []

        for _, row in to_match.iterrows():
            sname = row["SNAME"]
            print(f"[Processing {process_num} / {process_total}]\t{sname}")

            # Check for taxon in overrides list
            override_row = overrides_df[overrides_df["ELCODE"] == row["ELCODE"]].head(1)
            if len(override_row):
                new_row = override_row.iloc[0].to_dict()
                new_rows.append(new_row)
                process_num += 1
                continue

            taxon_id, matched_name = self.get_taxon_info(sname)

            # Clean up taxon ID
            if taxon_id and not pd.isna(taxon_id) and str(taxon_id).lower() != "nan":
                try:
                    clean_taxon_id = int(float(taxon_id))
                except (ValueError, TypeError):
                    clean_taxon_id = None
            else:
                clean_taxon_id = None
            
            # Copy all existing fields from tracking_df
            new_row = row.to_dict()
            # Add / overwrite mapping fields
            new_row["taxon_id"] = clean_taxon_id
            new_row["iNat_name"] = matched_name

            new_rows.append(new_row)
            process_num += 1
            # Be kind to the API
            time.sleep(1)

        if new_rows:
            mappings_df = pd.concat([mappings_df, pd.DataFrame(new_rows)], ignore_index=True)
        
        mappings_df = mappings_df.drop_duplicates(subset="SNAME", keep="last")
        mappings_df.to_csv(out_mapping_file, index=False)

        self.update_latest_cache(out_mapping_file)





def main():
    builder = TaxonCacheBuilder()
    builder.setup_access()
    builder.build_cache()


if __name__ == "__main__":
    main()