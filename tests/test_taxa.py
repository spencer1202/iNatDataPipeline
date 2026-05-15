import pytest
import configparser
import time
import os
import pandas as pd

from inatdatapipeline.taxa import TaxonMappingBuilder
import inatdatapipeline.db_manager as db_manager

config = "config.ini"

tracking_file = "taxonomy/tracking_lists/all_tracked.csv"
mapping_file = "tests/test_mappings.csv"
overrides_file = "taxonomy/name_maps/name_overrides.csv"


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
        processed_name = TaxonMappingBuilder.preprocess_name(name)
        assert processed_name == expected


def test_preprocess_long():
    tracking_df = pd.read_csv("taxonomy/tracking_lists/all_tracked.csv", usecols=["SNAME"])

    for name in tracking_df["SNAME"].to_list():
        result = TaxonMappingBuilder.preprocess_name(name)
        #print(f"Before: {name:<50}After: {result}")
        assert TaxonMappingBuilder.preprocess_name(name)


def test_build():
    builder = TaxonMappingBuilder(db_manager.DBManager("inat.db"))
    df = builder.build_mapping(
        tracking_file,
        overrides_file,
        False
    )
    print(df)
    print(f"\n{df[~df["exact_match"]]}")