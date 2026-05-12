#!/usr/bin/env python3
import os
import logging
import requests
from typing import Tuple, Optional
import pandas as pd
import datetime
import numpy as np
import re
import time

from helpers import iNaturalistAuth
from db_manager import DBManager

logger = logging.getLogger('pipeline')

class TaxonMappingBuilder:
    def __init__(self, db_manager: DBManager):
        self.db_manager = db_manager
    
    @staticmethod
    def query_taxon(scientific_name: str, auth: iNaturalistAuth) -> Tuple[Optional[int], Optional[str]]:
        """
        Get taxon_id and matched name for a scientific name using iNaturalist API
        
        Args:
            scientific_name: The scientific name to look up
            
        Returns:
            Tuple of (taxon_id, matched_name) if found, (None, None) otherwise
        """

        url = "https://api.inaturalist.org/v2/taxa"
        
        headers = auth.get_auth_headers()

        params = {
            "q"         : scientific_name,
            "per_page"  : 5,
            "order"     : "desc",
            "order_by"  : "observations_count",
            "fields"    : ["name", "id"]
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
    def insert_overrides(tracking_df: pd.DataFrame, overrides_df: pd.DataFrame):
        """
        Creates new column "sname_clean" in tracking_df and populates it with the name overrides present in overrides_df
        Args:
            tracking_df:
                Dataframe of tracking list.
            overrides_df:
                Dataframe of name overrides.
        Returns:
            Updated version of tracking_df
        """
        tracking_df["sname_clean"] = None
        tracking_df["sname_clean"] = tracking_df["est_id"].map(overrides_df.set_index("est_id")["inat_name"])

        return tracking_df
    
    
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
        
        # Regular expression that extracts the genus name, species name, and subspecies name or 
        # subspecies/population number.
        expr = r"^((?:[a-zA-Z\-]+[ \t]){1,2})(?:(?:var\.|pop\.|ssp\.|sp\.)\s)?(.+)?"
        match = re.search(expr, name.strip())
        if not match:       # some weird edge case
            return None
        
        processed_name = match.group(1) + match.group(2)

        # Clean up any double spaces
        while "  " in processed_name:
            processed_name = processed_name.replace("  ", " ")
        
        return processed_name.strip()

    
    @staticmethod
    def preprocess(df: pd.DataFrame):
        """
        Fills the sname_clean column with clean versions of each taxon name.
        """
        df["sname_clean"] = np.where(
            df["sname_clean"].isna(),
            df["sname"].apply(TaxonMappingBuilder.preprocess_name),
            df["sname_clean"]
        )
        return df


    @staticmethod
    def get_undescribed_names(df: pd.DataFrame) -> pd.DataFrame:
        # Matches names with a number at the end, grabs all text before the number
        expr = r"^((?:[A-Za-z\-]+[\t ])+)\d+$"
        generic_names = df["sname_clean"].str.extract(expr, expand=False).str.strip()
        df["exact_match"] = generic_names.isna()
        df.update({"sname_clean": generic_names})
        return df


    @staticmethod
    def rename_tracking_cols(df: pd.DataFrame) -> pd.DataFrame:
        col_renames = {
            "SNAME"                     : "sname", 
            "ELCODE"                    : "elcode", 
            "ELEMENT_SUBNATIONAL_ID"    : "est_id",
            "SCOMNAME"                  : "scomname"
        }

        return df.rename(columns=col_renames)

    @staticmethod
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


    @staticmethod
    def get_new_mappings(df: pd.DataFrame, auth: iNaturalistAuth) -> pd.DataFrame:
         # Process unmatched rows
        process_total = len(df)
        process_num = 1
        new_rows = []
        undescribed_names: dict[tuple[int, str]] = {}
        
        # Get timestamp
        today = datetime.date.today()

        #################### Querying ####################
        logger.info("Beginning taxon queries...")
        for _, row in df.iterrows():
            sname = row["sname_clean"]
            logger.info(f"{process_num:>4} / {process_total}\t{sname}")

            # Check if this is an undescribed taxon, and if so if it has already been mapped.
            if row["exact_match"]:
                taxon_id, matched_name = TaxonMappingBuilder.query_taxon(sname, auth)
            else:
                if not undescribed_names.get(sname):
                    taxon_id, matched_name = TaxonMappingBuilder.query_taxon(sname, auth)
                    undescribed_names[sname] = (taxon_id, matched_name)
                else:
                    taxon_id, matched_name = undescribed_names.get(sname)

            clean_id = TaxonMappingBuilder.clean_taxon_id(taxon_id)
            
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

        return pd.DataFrame(new_rows)

    
    def build_mapping(self, tracking_file: str, overrides_file: str, auth: iNaturalistAuth, force_rebuild: bool = False):
        logger.info("*** Running TaxonCacheBuilder ***")
        logger.info("---------------------------------")


        # Import overrides list
        try:
            overrides_df: pd.DataFrame = pd.read_csv(overrides_file)
        except FileNotFoundError as err:
            logger.error(f"Could not find overrides file: {overrides_file}.")
            return
        logger.info(f"Loaded {len(overrides_df)} name overrides from {overrides_file}.")

        # Import and clean tracking list
        try:
            tracking_df: pd.DataFrame = pd.read_csv(tracking_file)
        except FileNotFoundError as err:
            logger.error(f"Could not find tracking file: {tracking_file}.")
            return
        logger.info(f"Loaded {len(tracking_df)} taxa from tracking list {tracking_file}.")
        tracking_df = TaxonMappingBuilder.rename_tracking_cols(tracking_df)

        logger.info("Inserting name overrides...")
        tracking_df = TaxonMappingBuilder.insert_overrides(tracking_df, overrides_df)
        overrides_count = len(tracking_df[tracking_df["sname_clean"].notna()])
        logger.info(f"Updated {overrides_count} names.")
        logger.info("Preprocessing scientific names...")
        tracking_df = TaxonMappingBuilder.preprocess(tracking_df)

        # Make sure database is set up
        with self.db_manager as db:
            db.setup_db()

        # Create mapping dataframe, either with prior entries or from scratch
        if not force_rebuild:
            logger.info("Loading existing mappings...")
            with self.db_manager as db:
                mapping_df = db.get_mappings()
            logger.info(f"Retrieved {len(mapping_df)} taxon mappings from database.")
        else:
            logger.info("Rebuilding taxon mappings from scratch...")
            mapping_df = pd.DataFrame(columns=["est_id", "elcode", "sname", "scomname", "taxon_id", "inat_name"])

        match_mask = tracking_df["est_id"].isin(mapping_df["est_id"])
        to_match = tracking_df[~match_mask]
        if len(to_match) == 0:
            logger.info("All taxa on tracking list are already present in mappings.")
        else:
            logger.info(f"Found {len(to_match)} tracking list entries not present in existing mappings.")
            to_match = TaxonMappingBuilder.get_undescribed_names(to_match)
            logger.info(f"Undescribed taxa: {len(to_match[~to_match["exact_match"]])}")
            
            new_mappings = TaxonMappingBuilder.get_new_mappings(to_match, auth)

            with self.db_manager as db:
                db.insert_mappings(new_mappings)

        logger.info("Done!")
        logger.info("----------------------------------\n")