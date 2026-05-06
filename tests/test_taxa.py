import pytest
import configparser
import time
import pandas as pd

from pipeline.taxa import TaxonCacheBuilder

config = "config.ini"


def test_config():
    builder = TaxonCacheBuilder(config)

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
    builder = TaxonCacheBuilder(config)

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
        processed_name = builder.preprocess_name(name)
        assert processed_name == expected


def test_preprocess_long():
    tracking_df = pd.read_csv("taxonomy/tracking_lists/all_tracked_species.csv", usecols=["SNAME"])

    for name in tracking_df["SNAME"].to_list():
        result = TaxonCacheBuilder.preprocess_name(name)
        print(f"Before: {name:<50}After: {result}")
        assert TaxonCacheBuilder.preprocess_name(name)