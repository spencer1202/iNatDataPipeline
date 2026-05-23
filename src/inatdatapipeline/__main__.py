"""
TODO insert description of iNatDataPipeline tool

"""

import logging
from configparser import ConfigParser
import click
from pathlib import Path
from typing import Optional
import pandas as pd

import src.inatdatapipeline.taxa as taxa
import src.inatdatapipeline.helpers as helpers
import src.inatdatapipeline.config as config
from src.inatdatapipeline.project_members import ProjectMembers
from src.inatdatapipeline.inaturalist_auth import iNaturalistAuth
from src.inatdatapipeline.db_manager import DBManager
from src.inatdatapipeline.observations import ObservationQuery

logger = logging.getLogger('pipeline')
logger.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db(db_file: Path) -> DBManager:
    """
    Set up a database manager object
    """
    try:
        return DBManager(db_file)
    except Exception as err:
        helpers.error(logger, "Failed to connect to file database.")


def get_auth(user_agent: str, username: str) -> iNaturalistAuth:
    """
    Set up an iNaturalist authentication object
    """
    try:
        auth: iNaturalistAuth = iNaturalistAuth(user_agent)
        auth.generate_access_token(username)
    except Exception as err:
        helpers.error(logger, "Failed to generate access token.")
    if not auth.get_access_token():
        helpers.error(logger, "Could not obtain OAuth2 access token.")

    return auth


def parse_config(config_path: str) -> ConfigParser:
    """
    Parse config file and replace options with arguments where specified.

    Args:
        args: Namespace object from argparser
    Returns:
        ConfigParser object loaded with config options
    """
    try:
        cf = ConfigParser()
        cf.read(config_path)
        return cf
    
    except Exception as err:
        logger.error(f"Failed to load config file: {config_path}")
        raise click.ClickException(err)


def _done():
    logger.info("")
    logger.info("Done!")
    logger.info("---------------------------------------\n")


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group(help="CLI tool to manage iNaturalist data import pipeline")
@click.option(
    "--config", "config_path",
    type=click.Path(exists=True),
    default="config.ini",
    envvar="INAT_CONFIG",
    help="Path to config file."
)
@click.option(
    "--username", 
    envvar="INAT_USERNAME",
    default=None,
    help="iNaturalist username (overrides config)"
)
@click.option(
    "--db",
    type=click.Path(exists=False),
    envvar="OBSERVATION_DATABASE",
    default=None,
    help="Database file path (overrides config)"
)
@click.pass_context
def main(ctx: click.Context, username: str | None, db: str | None, config_path: str | None):
    helpers.logging_setup(logger, "logs", "pipeline.log")

    # Read config file
    try:
        cf = ConfigParser()
        cf.read(config_path)
    except Exception as err:
        print(f"Failed to load config file: {config_path}")
        raise click.ClickException(err)
    
    # Set up click CLI context
    raw_config = {section: dict(cf[section]) for section in cf.sections()}
    raw_config.setdefault("core", {})
    raw_config.setdefault("observations", {})
    raw_config.setdefault("taxa", {})
    raw_config.setdefault("review", {})
    raw_config.setdefault("overrides", {})

    if db is not None:
        raw_config["core"]["db_file"] = db
    
    ctx.obj = raw_config

    logger.info("---------------------------------------")
    logger.info("*** iNaturalist Data Pipeline Tool  ***")
    logger.info("---------------------------------------")
    logger.info(f"File database: {raw_config["core"]["db_file"]}")
    logger.info("")


# ---------------------------------------------------------------------------
# Build Taxon Map
# ---------------------------------------------------------------------------

@main.command("build-taxon-map")
@click.option(
    "--tracking", 
    default=None,
    help="Tracking list file (overrides config value)"
)
@click.option(
    "--rebuild", 
    is_flag=True,
    default=False,
    help="Force rebuild the taxon mapping from scratch (not recommended)"
)
@click.pass_context
def build_taxon_map(ctx: click.Context, tracking: str | None, rebuild: bool = False):
    """
    Build a taxon mapping and insert it into the local database.
    """
    logger.info("Building taxon map...")

    # Inject config override
    if tracking is not None:
        ctx.obj["taxa"]["tracking_list"] = tracking

    # Validate configs
    cfg_core, cfg_taxa = config.validate_command_config(ctx, "taxa", config.TaxaConfig)

    db_manager = get_db(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)
    taxon_mapper = taxa.TaxonMappingBuilder(db_manager)

    # Make sure database is set up
    with db_manager as db:
        db.setup_db()

    taxon_mapper.build_mapping(
        cfg_taxa.tracking_list,
        cfg_taxa.name_overrides_file,
        auth,
        rebuild
    )

    _done()


# ---------------------------------------------------------------------------
# Download Observations
# ---------------------------------------------------------------------------

@main.command("download-observations")
@click.option(
    "--days-since-update", "days_since_update",
    default=None,
    help="How many days since a taxon was last searched to update."
)
@click.pass_context
def download_observations(ctx: click.Context, days_since_update: Optional[int] = None):
    """
    Download observations, identifications, and users into local database.
    """
    logger.info("Downloading observations...")
    
    #  Inject config override
    if days_since_update is not None:
        ctx.obj["observations"]["update_after_days"] = days_since_update
    
    # Validate config
    cfg_core, cfg_obs = config.validate_command_config(ctx, "observations", config.ObservationsConfig)
    
    db_manager = get_db(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)
    
    # Make sure database is set up
    with db_manager as db:
        db.setup_db()

    observation_querier = ObservationQuery(db_manager, cfg_obs)
    observation_querier.get_observations(auth)

    _done()


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

@main.command("review")
@click.option("--export-csv", "export_csv",
    default=None,
    help="File to export reviewed observations to (will be overwritten)"
)
@click.pass_context
def review(ctx: click.Context, export_csv: str):
    """Export data from local database"""
    logger.info("Export - not implemented yet!")

    # Inject config override
    if export_csv is not None:
        ctx.obj["review"]["export_csv"] = export_csv

    # Validate config
    cfg_core, cfg_review = config.validate_command_config(ctx, "review", config.ReviewConfig)

    db_manager = get_db(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)

    # Make sure database is set up
    with db_manager as db:
        db.setup_db()
        expert_ids_df = db.get_expert_identifications()
        observations_df = db.get_observations()


    _done()


# ---------------------------------------------------------------------------
# Project Members
# ---------------------------------------------------------------------------

@main.command("update-project-members")
@click.pass_context
def project_members(ctx: click.Context):
    """
    Query for project members and update database table
    """
    # Validate config
    cfg_core, cfg_obs = config.validate_command_config(ctx, "observations", config.ObservationsConfig)
    
    logger.info(f"Updating current members in project: {cfg_obs.project_id}")

    querier = ProjectMembers(cfg_obs.project_id, cfg_obs.per_page)
    db_manager = get_db(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)
    
    # Make sure database is set up
    with db_manager as db:
        db.setup_db()
    
    querier.run(db_manager, auth)

    _done()


# ---------------------------------------------------------------------------
# Setup Database
# ---------------------------------------------------------------------------

@main.command("setup-database")
@click.pass_context
def setup_database(ctx: click.Context):
    """
    Set up database schema
    """
    logger.info(f"Setting up database...")

    # Validate config
    cfg, _ = config.validate_command_config(ctx)
    
    db_manager = get_db(cfg.db_file)
    with db_manager as db:
        db.setup_db()
    
    _done()


# ---------------------------------------------------------------------------
# Update Experts
# ---------------------------------------------------------------------------

@main.command("update-experts")
@click.option(
    "--expert-list", "expert_list",
    default=None,
    help="Experts list file (overrides config value)"
)
@click.pass_context
def update_experts(ctx: click.Context, expert_list: Optional[str]):
    """
    Replace experts list
    """
    # Inject config override
    if expert_list:
        ctx.obj["review"]["csv_file"] = expert_list

    # Validate config
    cfg_core, cfg_review = config.validate_command_config(ctx, "review", config.ReviewConfig)

    experts_df = pd.read_csv(cfg_review.experts_file)
    experts_df = experts_df.dropna(subset=["iNaturalist_id"])

    db_manager = get_db(cfg_core.db_file)
    with db_manager as db:
        count = db.update_experts(experts_df)

    logger.info(f"Inserted {count} experts!")


# ---------------------------------------------------------------------------
# Get Biotics tracking query
# ---------------------------------------------------------------------------
@main.command("biotics-query")
@click.pass_context
def biotics_query(ctx: click.Context):
    """
    Print the tracking list query for Biotics
    """
    query = """
        select 
            to_char(est.element_subnational_id) "name", 
            sname.scientific_name||' : '|| est.s_primary_common_name as "label", 
            sname.scientific_name "sname", sname.author_name as "author", 
            est.s_primary_common_name "scomname", 
            est.s_rank "s_rank", 
            D_EO_TRACK_STATUS.eo_track_status_desc "eo_track_status_desc", 
            'https://explorer.natureserve.org/Taxon/ELEMENT_GLOBAL.'||egt.element_global_ou_uid||'.'||egt.element_global_seq_uid as "explorer", 
            'ELEMENT_GLOBAL.'||egt.element_global_ou_uid||'.'||egt.element_global_seq_uid as "egt_uid", 
            hcu_f.higher_class_unit_name AS "family", 
            egt.elcode_bcd as elcode_bcd, 
            nc.name_category_desc,
            delimlist(
                'SELECT dgh.growth_habit_desc' 
                || ' FROM D_GROWTH_HABIT dgh, PLANT_CAG_GROWTH_HABIT gh' 
                || ' WHERE gh.d_growth_habit_id = dgh.d_growth_habit_id (+) and gh.element_global_id (+) = ' 
                || egt.element_global_id
            ) "growth_habit",
            case when egt.elcode_bcd like 'A%' or egt.elcode_bcd like 'I%' then 'Animal'
                when egt.elcode_bcd like 'P%' or egt.elcode_bcd like 'N%' then 'Plant'
                when egt.elcode_bcd like 'C%' or egt.elcode_bcd like 'G%' then 'Community'
            end "element_type",
            d_duration.duration_desc "duration"
        from 
            element_subnational est, 
            scientific_name sname, 
            element_global egt, 
            element_national ent, 
            D_EO_TRACK_STATUS, 
            higher_class_unit hcu, 
            higher_class_unit hcu_f, 
            D_NAME_CATEGORY nc, 
            d_duration, 
            plant_cag_duration pcd, 
            plant_cag
        where est.sname_id = sname.scientific_name_id 
            and est.element_national_id=ent.element_national_id 
            and ent.element_global_id=egt.element_global_id 
            and egt.higher_class_unit_id = hcu.higher_class_unit_id(+)
            and hcu.parent_unit_id = hcu_f.higher_class_unit_id(+)
            and est.d_eo_track_status_id = D_EO_TRACK_STATUS.d_eo_track_status_id (+)
            and sname.D_NAME_CATEGORY_id = nc.D_NAME_CATEGORY_id (+)
            and egt.element_global_id = plant_cag.element_global_id (+)
            and plant_cag.element_global_id = pcd.element_global_id (+)
            and pcd.d_duration_id = d_duration.d_duration_id (+)
            and D_EO_TRACK_STATUS.eo_track_status_desc = 'Track all extant and selected historical EOs'
        order by scientific_name
        """
    print(query)

    _done()


if __name__ == "__main__":
    main()

