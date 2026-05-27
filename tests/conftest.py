import pytest
import logging

from inatdatapipeline.observations import ObservationQuery
import inatdatapipeline.config as config
from inatdatapipeline.db_manager import DBManager
from inatdatapipeline.request_helpers import INaturalistAuth

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def logger():
    logger = logging.getLogger('pipeline')
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logger.addHandler(console_handler)


@pytest.fixture(scope="session")
def core_cfg():
    return config.CoreConfig(
        db_file     = "data/test_small.db",
        user_agent  = "iNat_ORBIC_DataPipeline/1.0",
        username    = "hspencer1202"
    )

@pytest.fixture(scope="session")
def obs_cfg():
    return config.ObservationsConfig(
        place_id            = 10,
        quality_grade       = "research",
        per_page            = 200,
        batch_size          = 15,
        fields_json         = "src/inatdatapipeline/obs_fields.json",
        update_after_days   = 30,
        project_id          = 247148,
        max_observations    = 10000
    )

@pytest.fixture(scope="session")
def tax_cfg():
    return config.TaxaConfig(
        tracking_list = "data/taxonomy/elcode_tracking_k.csv",
        name_overrides_file = "data/taxonomy/name_overrides.csv",
    )

@pytest.fixture(scope="session")
def rev_cfg():
    return config.ReviewConfig(
        experts_file = "data/experts/Master_iNaturalist_US_Canada_Experts_20240327.csv",
        export_csv = "data/output/observations.csv"
    )


@pytest.fixture(scope="session")
def observation_results(core_cfg, obs_cfg):
    obs_cfg.update_after_days = 0
    querier = ObservationQuery(obs_cfg)
    db_manager = DBManager(core_cfg.db_file)
    auth = INaturalistAuth(core_cfg.user_agent)
    auth.generate_access_token(core_cfg.username)

    with db_manager as db:
        taxa_df = db.get_inat_taxa()
    
    return {
        "querier": querier,
        "db": db_manager,
        "auth": auth,
        "taxa": taxa_df,
        "results": querier.fetch_observations(auth, taxa_df)
    }
