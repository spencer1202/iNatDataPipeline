import pytest
import configparser
import time
import os
import pandas as pd

import pipeline.taxa as taxa

config = "config.ini"

tracking_file = "taxonomy/tracking_lists/all_tracked_species.csv"
mapping_file = "tests/test_mappings.csv"
overrides_file = "taxonomy/name_maps/name_overrides.csv"


def test_config():
    builder = taxa.TaxonCacheBuilder(config)

    print(builder.config.sections())

    assert builder.config_file == "config.ini"
    assert builder.config.has_section("scraper")
    assert builder.config.has_section("taxon_map")
    assert builder.config.has_section("date")
    assert builder.config.has_section("experts")
    assert builder.config.has_section("authentication")

    assert int(builder.config["scraper"]["place_id"]) == 10
    assert builder.config["scraper"]["quality_grade"] == "research"
    assert int(builder.config["scraper"]["per_page"]) == 200
    assert builder.config["taxon_map"]["tracking_list"].startswith("taxonomy/tracking_lists/")



def test_preprocess():
    names = {
        "Plagiochila semidecurrens var. semidecurrens"  : "Plagiochila semidecurrens semidecurrens",
        "Stegonia latifolia var. pilifera"              : "Stegonia latifolia pilifera",
        "Hymenoxys cooperi var. canescens"              : "Hymenoxys cooperi canescens",
        "Plagiochila semidecurrens var. semidecurrens"  : "Plagiochila semidecurrens semidecurrens",
        "Stegonia latifolia var. pilifera"              : "Stegonia latifolia pilifera",
        "Hymenoxys cooperi var. canescens"              : "Hymenoxys cooperi canescens",
        "Ptychoramphus aleuticus"                       : "Ptychoramphus aleuticus",
        "Sardinops sagax"                               : "Sardinops sagax",
        "Falco peregrinus tundrius"                     : "Falco peregrinus tundrius",
        "Salvelinus confluentus pop. 25"                : "Salvelinus confluentus 25",
        "Rhinichthys klamathensis pop. 1"               : "Rhinichthys klamathensis 1",
        "Siphateles bicolor ssp. 1"                     : "Siphateles bicolor 1",
        "Silene hookeri ssp. serpentinicola"            : "Silene hookeri serpentinicola",
        "Sidalcea malviflora ssp. patula"               : "Sidalcea malviflora patula",
        "Sidalcea hickmanii ssp. petraea"               : "Sidalcea hickmanii petraea"   
    }
    
    for name, expected in names.items():
        processed_name = taxa.preprocess_name(name)
        assert processed_name == expected


def test_preprocess_long():
    tracking_df = pd.read_csv("taxonomy/tracking_lists/all_tracked_species.csv", usecols=["SNAME"])

    for name in tracking_df["SNAME"].to_list():
        result = taxa.preprocess_name(name)
        #print(f"Before: {name:<50}After: {result}")
        assert taxa.preprocess_name(name)


def test_load_tracking_list_success():
    tracking_file = "taxonomy/tracking_lists/all_tracked_species.csv"

    tracking_df: pd.DataFrame = taxa.load_tracking_list(tracking_file)
    assert [col in tracking_df.columns for col in ["sname", "scomname", "elcode"]]
    #print(tracking_df.info())


def test_load_tracking_list_failure():
    # Non existent file
    with pytest.raises(FileNotFoundError):
        tracking_df = taxa.load_tracking_list("not_a_file.csv")
    
    # File without correct columns
    with pytest.raises(KeyError):
        tracking_df = taxa.load_tracking_list("tests/bad.csv")


def test_load_mappings_success():
    cols = [
        "sname",
        "elcode",
        "taxon_id",
        "inat_name",
        "last_updated",
        "sname_clean"
    ]
      
    map_file = "tests/test_mappings.csv"
    assert os.path.exists(map_file)
    mappings_df = taxa.load_mapping_list(map_file)
    assert len(mappings_df) == 86
    assert [col in mappings_df.columns for col in cols]
    
    mappings_df = taxa.load_mapping_list("not_a_file")
    assert len(mappings_df) == 0
    assert [col in mappings_df.columns for col in cols]

    mappings_df = taxa.load_mapping_list()
    assert len(mappings_df) == 0
    assert [col in mappings_df.columns for col in cols]


def test_get_to_match_list():
    tracking_df = taxa.load_tracking_list(tracking_file)
    mapping_df = taxa.load_mapping_list(mapping_file)
    to_match = taxa.get_to_match_list(tracking_df, mapping_df)
    
    assert len(to_match) <= len(tracking_df)
    assert len(to_match[to_match["elcode"].isin(mapping_df["elcode"])]) == 0


def test_setup_dfs():
    tracking_df, mapping_df, overrides_df = taxa.setup_dfs(
        tracking_file, mapping_file, overrides_file
    )

def test_name_overrides():
    tracking_df, mapping_df, overrides_df = taxa.setup_dfs(
        tracking_file, mapping_file, overrides_file
    )
    to_match = taxa.get_to_match_list(tracking_df, mapping_df)
    to_match["sname_clean"] = taxa.get_name_overrides(to_match, overrides_df)
    print(to_match[to_match["sname_clean"].notna()])

"""
def setup_dfs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    
    Returns the three main dataframes (in order): tracking_df, mapping_df, to_match
    
    tracking_df = taxa.load_tracking_list("taxonomy/tracking_lists/all_tracked_species.csv")
    mapping_df = taxa.load_mapping_list("tests/test_mappings.csv")
    to_match = taxa.get_to_match_list(tracking_df, mapping_df)
    return tracking_df, mapping_df, to_match
"""