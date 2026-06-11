"""
This module handles building a mapping between the Biotics and iNaturalist taxon entries.
"""

#!/usr/bin/env python3
import logging
from typing import Optional
import datetime
import re
import time
from dataclasses import dataclass, field
import requests
import pandas as pd
import numpy as np

from inatdatapipeline.client.authentication import INaturalistAuth, TIMEOUT

# Set up logging
logger = logging.getLogger('pipeline')


@dataclass
class Taxon:
    """
    Object representing an iNaturalist taxon
    """
    taxon_id: int
    name: str


@dataclass
class TaxonResult:
    """
    The results of taxon request, with a best match "primary" taxon and a possibly empty list of 
    alternative taxa.
    """
    primary: Optional[Taxon] = None
    alternatives: list[Taxon] = field(default_factory=list)


@dataclass
class MappingResult:
    """
    The results of building a taxon mapping. 

    * **new_mappings**: Dataframe with new taxon mappings.
    * **alt_names**:  Dataframe with alternative names for taxa that have them.
    """
    new_mappings: Optional[pd.DataFrame] = None
    alt_names: Optional[pd.DataFrame] = None


# ---------------------------------------------------------------------------
# Taxon Mapping Builder
# ---------------------------------------------------------------------------
class TaxonMappingBuilder:
    """
    This class is responsible for building a taxon mapping by requesting iNaturalist taxon names
    and IDs from the iNaturalist Taxa API endpoint.
    """
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
            response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return None

        except requests.RequestException as ex:
            logger.error("Error looking up '%s': %s", scientific_name, str(ex))
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
                logger.error("Taxon ID '%s' is not valid.", result_id)
                continue

            # Handle NaN values and ensure we have valid data
            if (
                pd.isna(result_name)
                or pd.isna(result_id_int)
                or not result_name
                or not result_id_int
            ):
                continue
            if not isinstance(result_name, str):
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
    def preprocess(tracking_df: pd.DataFrame, overrides_df: pd.DataFrame) -> pd.DataFrame:
        """
        Preprocess taxon names by inserting name overrides, cleaning the names, and marking
        undescribed taxa.
        """
        logger.debug("Inserting name overrides...")
        tracking_df["sci_name_clean"] = None
        tracking_df["sci_name_clean"] = (
            tracking_df["est_id"]
            .map(overrides_df.set_index("est_id")["inat_name"])
        )
        overrides_count = len(tracking_df[tracking_df["sci_name_clean"].notna()])
        logger.debug("* Updated %i names.", overrides_count)

        # Preprocess names
        logger.debug("Preprocessing scientific names...")

        tracking_df["sci_name_clean"] = np.where(
            tracking_df["sci_name_clean"].isna(),
            tracking_df["sci_name"].apply(TaxonMappingBuilder.preprocess_name),
            tracking_df["sci_name_clean"]
        )

        # Mark undescribed names
        tracking_df = TaxonMappingBuilder.get_undescribed_names(tracking_df)
        logger.debug("Undescribed taxa: %i", len(tracking_df[~tracking_df["exact_match"]]))

        return tracking_df


    @staticmethod
    def get_undescribed_names(df: pd.DataFrame) -> pd.DataFrame:
        """
        Extracts generic names for all undescribed taxa and marks exact matches (not undescribed)
        """
        # Matches names with a number at the end, grabs all text before the number
        expr = r"^((?:[A-Za-z\-]+[\t ])+)\d+$"
        generic_names = df["sci_name_clean"].str.extract(expr, expand=False).str.strip()
        df["exact_match"] = generic_names.isna()
        df.update({"sci_name_clean": generic_names})
        return df

    @staticmethod
    def get_new_mappings(df: pd.DataFrame, auth: INaturalistAuth) -> Optional[MappingResult]:
        """
        Get taxon mappings by querying for the taxa in the provided dataframe. Structures responses
        into dataframes and validates them.

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
        today = datetime.datetime.today()

        #################### Querying ####################
        for _, row in df.iterrows():
            taxon: TaxonResult = None
            sname = row["sci_name_clean"]
            logger.info("%4i / %i\t%s", process_num, process_total, sname)

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
                time.sleep(1)
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

        if len(new_taxa) == 0:
            return None

        return MappingResult(
            new_mappings = pd.DataFrame(new_taxa),
            alt_names = (
                pd.DataFrame(alternative_taxa)
                if len(alternative_taxa) > 0 else None
            )
        )


    def build_mapping(
            self,
            tracking_df: pd.DataFrame,
            auth: INaturalistAuth,
            mapping_df: Optional[pd.DataFrame]
    ) -> Optional[MappingResult]:
        """
        Build a taxon mapping from the given tracking file including the existing mappings in 
        mapping_df. Return the new mappings in a MappingResult object.
        """
        if tracking_df is None or len(tracking_df) == 0:
            raise ValueError("Tracking dataframe must not be None or empty.")

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
            return None

        logger.debug("* Found %i tracking list entries not present in existing mappings.",
                     len(to_match))

        # Generate new mappings
        logger.info("")
        logger.info("Beginning taxon queries...")
        return TaxonMappingBuilder.get_new_mappings(to_match, auth)
