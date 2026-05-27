"""
This module handles building a mapping between the Biotics and iNaturalist taxon entries.
"""

#!/usr/bin/env python3
import os
import logging
import requests
from typing import Tuple, Optional, NamedTuple, Self
import pandas as pd
import datetime
import numpy as np
import re
import time
from dataclasses import dataclass, field
from sqlite3 import DatabaseError

from inatdatapipeline.request_helpers import INaturalistAuth
from inatdatapipeline.db_manager import DBManager

# Set up logging
logger = logging.getLogger('pipeline')

@dataclass
class Taxon:
    taxon_id: int
    name: str


@dataclass
class TaxonResult:
    primary: Optional[Taxon] = None
    alternatives: list[Taxon] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Taxon Mapping Builder
# ---------------------------------------------------------------------------
class TaxonMappingBuilder:
    def __init__(self, db_manager: DBManager):
        self.db_manager = db_manager
    
    @staticmethod
    def query_taxon(scientific_name: str, auth: INaturalistAuth) -> Optional[TaxonResult]:
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
                return None
        
        except requests.RequestException as e:
            logger.error(f"Error looking up '{scientific_name}': {e}")
            return None

        # Look for exact name match first
        taxon = TaxonResult()
        for result in results:
            result_name = result.get("name", "")
            result_id = result.get("id")

            # Convert result_id to an integer
            try:
                result_id_int = int(result_id)
            except TypeError:
                logger.error(f"Taxon ID '{result_id}' is not valid.")
                continue
            
            # Handle NaN values and ensure we have valid data
            if pd.isna(result_name) or pd.isna(result_id_int) or not result_name or not result_id_int:
                continue
            if type(result_name) != str:
                continue

            taxon.alternatives.append( Taxon(result_id_int, result_name) )

            if not taxon.primary and result_name.lower() == scientific_name.lower(): #exact match
                taxon.alternatives.pop()
                taxon.primary = Taxon(result_id_int, result_name)

        if not taxon.primary and len(taxon.alternatives) > 0:
            taxon.primary = taxon.alternatives.pop(0)
        
        if taxon.primary:
            return taxon
        return None
    
    
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
    def get_undescribed_names(df: pd.DataFrame) -> pd.DataFrame:
        # Matches names with a number at the end, grabs all text before the number
        expr = r"^((?:[A-Za-z\-]+[\t ])+)\d+$"
        generic_names = df["sci_name_clean"].str.extract(expr, expand=False).str.strip()
        df["exact_match"] = generic_names.isna()
        df.update({"sci_name_clean": generic_names})
        return df


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
    def get_new_mappings(df: pd.DataFrame, auth: INaturalistAuth) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Get taxon mappings by querying for the taxa in the provided dataframe.

        Returns:
            (mappings_df, alternatives_df):
                A dataframe of mappings between Biotics taxa and iNaturalist taxa, and a dataframe
                of alternative iNaturalist names.
        """
         # Process unmatched rows
        process_total = len(df)
        process_num = 1
        new_taxa = []
        alternative_taxa = []
        undescribed_names: dict[str, TaxonResult] = {}
        
        # Get timestamp
        today = datetime.date.today()

        #################### Querying ####################
        for _, row in df.iterrows():
            taxon: TaxonResult = None
            sname = row["sci_name_clean"]
            logger.info(f"{process_num:>4} / {process_total}\t{sname}")

            # Check if this is an undescribed taxon, and if so if it has already been mapped.
            if row["exact_match"]:
                taxon = TaxonMappingBuilder.query_taxon(sname, auth)
            else:
                if not undescribed_names.get(sname):
                    taxon = TaxonMappingBuilder.query_taxon(sname, auth)
                    undescribed_names[sname] = taxon
                else:
                    taxon = undescribed_names.get(sname)
            
            # No result found
            if not taxon:
                process_num += 1
                continue

            # Copy all existing fields from tracking_df
            new_taxon = row.to_dict()
            # Add / overwrite mapping fields
            new_taxon["taxon_id"] = taxon.primary.taxon_id
            new_taxon["inat_name"] = taxon.primary.name
            new_taxon["last_updated"] = today
            new_taxa.append(new_taxon)

            for tx in taxon.alternatives:
                new_alternative = {
                    "taxon_id": taxon.primary.taxon_id,
                    "alternative_taxon_id": tx.taxon_id,
                    "alternative_inat_name": tx.name
                }
                alternative_taxa.append(new_alternative)
            
            process_num += 1
            # Be kind to the API
            time.sleep(1)

        return (
            pd.DataFrame(new_taxa) if len(new_taxa) > 0 else None,
            pd.DataFrame(alternative_taxa) if len(alternative_taxa) > 0 else None
        )


    @staticmethod
    def get_tracking_df(tracking_file: str, overrides_file: str) -> pd.DataFrame | None:
        """
        Returns:
            Populated and cleaned tracking dataframe, or None on failure
        """
        try:
            logger.debug("Loading tracking list and name overrides...")
            overrides_df: pd.DataFrame = pd.read_csv(overrides_file, encoding="latin-1")
            tracking_df: pd.DataFrame = pd.read_csv(tracking_file, encoding="latin-1")
            logger.debug(f"* Loaded {len(tracking_df)} taxa from tracking list {tracking_file}.")
            logger.debug(f"* Loaded {len(overrides_df)} name overrides from {overrides_file}.")
        except Exception as ex:
            logger.error(f"Encountered error while loading overrides and/or tracking list: {ex}")
            return None
        
        cols = {
            "sname"                 : "sci_name",
            "name"                  : "est_id",
            "element_type"          : "element_type",
            "scomname"              : "common_name",
            "family"                : "family",
            "author"                : "author",
            "egt_uid"               : "egt_uid",
            "s_rank"                : "srank",
            "eo_track_status_desc"  : "track_status",
            "explorer"              : "explorer", 
            "ELCODE_BCD"            : "elcode",
            "growth_habit"          : "growth_habit",
            "duration"              : "duration"
        }

        # Validate expected columns
        try:
            actual_cols = tracking_df.columns
            for col in cols.keys():
                assert col in actual_cols, f"{col}"
        except AssertionError as err:
            logger.error(f"Tracking list is missing expected column: {err}")
            return None
        
        # Rename columns
        tracking_df = tracking_df.rename(columns=cols)
        
        # Add fields
        tracking_df["explorer_link"] = tracking_df["explorer"].apply(
            lambda x: f"<a href=\"{x}\">View in Explorer</a>"
        )
        tracking_df["scientific_name"] = tracking_df["sci_name"].apply(
            lambda x: f"<i>{x}</i>"
        )
        tracking_df["element_name"] = tracking_df["est_id"].astype(str)

        # Insert overrides
        logger.debug("Inserting name overrides...")
        tracking_df["sci_name_clean"] = None
        tracking_df["sci_name_clean"] = tracking_df["est_id"].map(overrides_df.set_index("est_id")["inat_name"])
        overrides_count = len(tracking_df[tracking_df["sci_name_clean"].notna()])
        logger.debug(f"* Updated {overrides_count} names.")

        # Preprocess names
        logger.debug("Preprocessing scientific names...")
        tracking_df["sci_name_clean"] = np.where(
            tracking_df["sci_name_clean"].isna(),
            tracking_df["sci_name"].apply(TaxonMappingBuilder.preprocess_name),
            tracking_df["sci_name_clean"]
        )

        return tracking_df
    
    
    def build_mapping(self, tracking_file: str, overrides_file: str, auth: INaturalistAuth, mapping_df: pd.DataFrame):

        # Import and clean tracking list
        tracking_df: pd.DataFrame = TaxonMappingBuilder.get_tracking_df(tracking_file, overrides_file)

        cols = [
            "sci_name", 
            "est_id", 
            "element_type",
            "scientific_name",
            "common_name",
            "element_name",
            "family",
            "author",
            "egt_uid",
            "srank",
            "track_status",
            "explorer",
            "explorer_link",
            "elcode", 
            "growth_habit",
            "duration",
            "taxon_id", 
            "inat_name",
        ]

        # Create mapping dataframe, either with prior entries or from scratch
        if mapping_df is None:
            mapping_df = pd.DataFrame(columns=cols)

        logger.debug("Filtering for taxa that don't have mappings yet...")
        match_mask = tracking_df["est_id"].isin(mapping_df["est_id"])
        to_match = tracking_df[~match_mask]

        if len(to_match) == 0:
            logger.warning("* All taxa on tracking list are already present in mappings.")
            return
        
        logger.debug(f"* Found {len(to_match)} tracking list entries not present in existing mappings.")
        to_match = TaxonMappingBuilder.get_undescribed_names(to_match)
        logger.debug(f"Undescribed taxa: {len(to_match[~to_match["exact_match"]])}")
        
        # Generate new mappings
        logger.info("")
        logger.info("Beginning taxon queries...")
        new_mappings, alternative_names = TaxonMappingBuilder.get_new_mappings(to_match, auth)

        # Insert mappings into database
        try:
            with self.db_manager as db:
                db.insert_mappings(new_mappings)
                db.insert_alternatives(alternative_names)
        except DatabaseError as err:
            logger.error(f"Failed to insert mappings into database: {err}")
        
  