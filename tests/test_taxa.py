import pandas as pd
import logging

from src.inatdatapipeline.taxa import TaxonMappingBuilder
from src.inatdatapipeline.db_manager import DBManager
from src.inatdatapipeline.inaturalist_auth import iNaturalistAuth

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
config = "config.ini"

tracking_file = "data/taxonomy/elcode_tracking_a.csv"
tracking_file_big = "data/taxonomy/all_tracked.csv"
overrides_file = "data/taxonomy/name_overrides.csv"
db_file = "data/test.db"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Set up logging
logger = logging.getLogger('pipeline')
# logger.setLevel(logging.DEBUG)

# console_handler = logging.StreamHandler()
# console_handler.setLevel(logging.DEBUG)
# console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

# logger.addHandler(console_handler)

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_preprocess_long():
    tracking_df = pd.read_csv(tracking_file_big, usecols=["sname"], encoding="latin-1")

    for name in tracking_df["sname"].to_list():
        result = TaxonMappingBuilder.preprocess_name(name)
        assert TaxonMappingBuilder.preprocess_name(name)


def test_build():
    builder = TaxonMappingBuilder(DBManager(db_file))
    auth = iNaturalistAuth()
    db = DBManager(db_file)
    with db as conn:
        mapping_df = db.get_mappings()
    
    if len(mapping_df) == 0:
        mapping_df = None

    df = builder.build_mapping(
        tracking_file,
        overrides_file,
        auth,
        mapping_df
    )


def test_get_tracking_df():
    db = DBManager(db_file)
    builder = TaxonMappingBuilder(db)

    df = builder.get_tracking_df(tracking_file, overrides_file)

    print(f"\n\n")
    print("-------------------------------------------")
    print(f"Tracking list: \n\n{df}\n")
    df.info()
    print("-------------------------------------------")