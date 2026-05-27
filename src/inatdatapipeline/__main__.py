"""
TODO insert description of iNatDataPipeline tool
"""

import sys
import logging
from configparser import ConfigParser
import click
from pathlib import Path
from typing import Optional, Any
import os
from requests import HTTPError
import pandas as pd
from sqlite3 import DatabaseError
from pydantic import ValidationError

import inatdatapipeline.taxa as taxa
import inatdatapipeline.config as config
from inatdatapipeline.request_helpers import (
    INaturalistAuth, FetchProjectMembers, FetchAnnotations
)
from inatdatapipeline.db_manager import DBManager
from inatdatapipeline.observations import ObservationQuery, ObservationsResult

logger = logging.getLogger('pipeline')
logger.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_db_and_auth(
        db_file: Path, 
        user_agent: str, 
        username: str
) -> tuple[Optional[DBManager], Optional[INaturalistAuth]]:
    """
    Set up database connection and iNaturalist authentication. Catches exceptions and exits
    with error message if one occurs.
    """
    try:
        auth: INaturalistAuth = INaturalistAuth(user_agent)
        success = auth.generate_access_token(username)
    # No app credentials
    except ValueError as ex:
        _exit_failure(ex)
    # Invalid credentials
    except HTTPError as ex:
        _exit_failure("Authentication failed: Invalid credentials.")
    
    if not success:
        _exit_failure("Could not obtain OAuth2 access token.")

    db = DBManager(db_file)

    return db, auth


def db_setup(db_manager: DBManager):
    """
    Helper function that sets up database tables, catches exceptions and exits with an error 
    message if one occurs.
    """
    try:
        with db_manager as db:
            db.setup_db()    
    except DatabaseError as ex:
        _exit_failure(ex)


def _exit_success():
    logger.info("")
    logger.info("Done!")
    logger.info("---------------------------------------\n")
    sys.exit(0)


def _exit_failure(msg: Any = None):
    """
    Optionally log an error message, then exit the program with an error code.
    """
    if msg:
        logger.error(str(msg))
    
    logger.info("")
    logger.info("Exiting.")
    logger.info("---------------------------------------\n")
    sys.exit(1)


def logging_setup(
        logger: logging.Logger, 
        log_folder: str = "logs", 
        log_file: str = "taxon_mapping.log",
        console_level: int = logging.INFO, 
        file_level: int = logging.DEBUG,
):
    # Make sure name maps folder exists
    os.makedirs(log_folder, exist_ok=True)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    file_handler = logging.FileHandler(os.path.join(log_folder, log_file))
    file_handler.setLevel(file_level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M")
    )

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

# pylint: disable=no-value-for-parameter
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
    logging_setup(logger, "logs", "pipeline.log")

    # Read config file
    try:
        cf = ConfigParser()
        with open(config_path, "r") as fp:
            cf.read_file(fp)
    except FileNotFoundError:
        _exit_failure(f"Could not find config file: {config_path}")
    
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
    try:
        cfg_core, cfg_taxa = config.validate_command_config(ctx, "taxa", config.TaxaConfig)
    except ValidationError as ex:
        _exit_failure(ex)

    # Get database and authentication
    db_manager, auth = get_db_and_auth(cfg_core.db_file, cfg_core.user_agent, cfg_core.username)
    db_setup(db_manager)
    
    taxon_mapper = taxa.TaxonMappingBuilder(db_manager)

    # Rebuild from scratch
    if rebuild:
        logger.info("Rebuilding taxon mappings from scratch...")
        mapping_df = None
    
    # Get existing mappings
    else:
        logger.info("Loading existing mappings...")
        try:
            with db_manager as db:
                mapping_df = db.get_mappings()
        except Exception as err:
            _exit_failure(f"Failed to load mappings: {err}")

        logger.debug(f"* Retrieved {len(mapping_df)} taxon mappings from database.")

    taxon_mapper.build_mapping(
        cfg_taxa.tracking_list,
        cfg_taxa.name_overrides_file,
        auth,
        mapping_df
    )

    _exit_success()


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
    
    # Inject config override
    if days_since_update is not None:
        ctx.obj["observations"]["update_after_days"] = days_since_update
    
    # Validate config
    try:
        cfg_core, cfg_obs = config.validate_command_config(
            ctx, "observations", config.ObservationsConfig
        )
    except ValidationError as ex:
        _exit_failure(ex)
    
    # Get database and authentication
    db_manager, auth = get_db_and_auth(cfg_core.db_file, cfg_core.user_agent, cfg_core.username)
    db_setup(db_manager)

    # Get iNat taxa from database
    try:
        with db_manager as db:
            taxa_df = db.get_inat_taxa()
    except Exception as err:
        _exit_failure(f"Failed to get iNaturalist taxa from database: {err}")

    # Make sure taxa df isn't empty
    if len(taxa_df) == 0:
        _exit_failure("No taxa found in database to download!")
    
    # Download observations
    observation_querier = ObservationQuery(cfg_obs)
    try:
        results = observation_querier.fetch_observations(auth, taxa_df)
    except ValueError as ex:
        _exit_failure(ex)
    
    logger.info("Finished downloading!")
    logger.info("")

    # Update database
    try:
        with db_manager as db:
            user_count = db.insert_users(results.users)
            obs_count = db.insert_observations(results.observations)
            ident_count = db.insert_identifications(results.identifications)
            db.update_checked_date(results.completed_taxa)
    except DatabaseError as err:
        _exit_failure(err)

    # Report results
    logger.info("Inserted new records into database:")
    logger.info(f"Users:            {user_count}")
    logger.info(f"Observations:     {obs_count}")
    logger.info(f"Identifications:  {ident_count}")

    _exit_success()


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
    """Export data from database"""
    # Inject config override
    if export_csv is not None:
        ctx.obj["review"]["export_csv"] = export_csv

    # Validate config
    try:
        cfg_core, cfg_review = config.validate_command_config(ctx, "review", config.ReviewConfig)
    except ValidationError as ex:
        _exit_failure(ex)

    # Get database and authentication
    db_manager = DBManager(cfg_core.db_file)
    db_setup(db_manager)

    with db_manager as db:
        expert_ids_df = db.get_expert_identifications()
        observations_df = db.get_full_observations()

    print(expert_ids_df.head(50))
    print("\n")
    print(observations_df.head(50))

    _exit_success()


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
    try:
        cfg_core, cfg_obs = config.validate_command_config(
            ctx, "observations", config.ObservationsConfig
        )
    except ValidationError as ex:
        _exit_failure(ex)
    
    logger.info(f"Updating current members in project: {cfg_obs.project_id}")

    db_manager, auth = get_db_and_auth(cfg_core.db_file, cfg_core.user_agent, cfg_core.username)
    db_setup(db_manager)

    member_ids = FetchProjectMembers(auth, cfg_obs.per_page, cfg_obs.project_id)
    logger.debug(f"Found {len(member_ids)} project members.")

    try:
        with db_manager as db:
            rows_inserted = db_manager.replace_project_members(member_ids)
    except DatabaseError as ex:
        _exit_failure(ex)

    logger.info(f"Inserted {rows_inserted} new member IDs.")
    _exit_success()


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
    try:
        cfg, _ = config.validate_command_config(ctx)
    except ValidationError as ex:
        _exit_failure(ex)

    db_manager = DBManager(cfg.db_file)
    db_setup(db_manager)
    
    _exit_success()


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
    try:
        cfg_core, cfg_review = config.validate_command_config(ctx, "review", config.ReviewConfig)
    except ValidationError as ex:
        _exit_failure(ex)

    experts_df = pd.read_csv(cfg_review.experts_file)
    experts_df = experts_df.dropna(subset=["iNaturalist_id"])

    db_manager = DBManager(cfg_core.db_file)
    with db_manager as db:
        count = db.update_experts(experts_df)

    logger.info(f"Inserted {count} experts.")

    _exit_success()


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

    _exit_success()


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------
@main.command("annotations")
@click.pass_context
def annotations(ctx: click.Context):
    """
    Set up the local database with all of the iNaturalist annotation options.
    """
    # Validate core config
    try:
        cfg_core = config.validate_command_config(ctx)[0]
    except ValidationError as ex:
        _exit_failure(ex)
    
    # Get database and authentication
    db_manager, auth = get_db_and_auth(cfg_core.db_file, cfg_core.user_agent, cfg_core.username)

    annotations, values = FetchAnnotations(auth)
    with db_manager as db:
        db.update_annotations(annotations, values)
    
    _exit_success()


if __name__ == "__main__":
    main()
