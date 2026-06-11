"""
TODO insert description of iNatDataPipeline tool
"""
#### Standard imports ####
import os
import sys
import logging
from configparser import ConfigParser
from typing import Optional, Any
import traceback
import sqlite3

#### Third-party imports ####
from requests import HTTPError
import click
from pydantic import ValidationError

#### Local imports ####
from inatdatapipeline import (
    db,
    pipeline,
)
from inatdatapipeline.schemas import config
from inatdatapipeline.client import authentication

#### Setup ####
logger = logging.getLogger('pipeline')
logger.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_auth(
        user_agent: str,
        username: str
) -> tuple[Optional[db.DBManager], Optional[authentication.INaturalistAuth]]:
    """
    Set up iNaturalist authentication using provided user agent and username. Catches exceptions 
    and exits with error message if one occurs.
    """
    try:
        auth: authentication.INaturalistAuth = authentication.INaturalistAuth(user_agent)
        success = auth.generate_access_token(username)
    # Invalid credentials
    except HTTPError as ex:
        raise ValueError("Authentication failed: Invalid credentials.") from ex

    if not success:
        raise ValueError("Could not obtain OAuth2 access token.")

    return auth


def db_setup(db_manager: db.DBManager):
    """
    Helper function that sets up database tables, catches exceptions and exits with an error 
    message if one occurs.
    """
    try:
        with db_manager as conn:
            conn.setup_db()
    except sqlite3.Error as ex:
        raise ValueError("Error while setting up database.") from ex


def _exit_success():
    logger.info("")
    logger.info("Done!")
    logger.info("---------------------------------------\n")
    sys.exit(0)


def _exit_failure(err: Any = None):
    """
    Optionally log an error message, then exit the program with an error code.
    """
    if err:
        msg_err = traceback.format_exception(None, value=err, tb=None, chain=True)
        msg_debug = traceback.format_exception(err)
        logger.error(str(msg_err))
        logger.debug(msg_debug)

    logger.info("")
    logger.info("Exiting.")
    logger.info("---------------------------------------\n")
    sys.exit(1)


def logging_setup(
        log: logging.Logger,
        log_folder: str = "logs",
        log_file: str = "taxon_mapping.log",
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
):
    """
    Set up console and file handlers for logging.
    """
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

    log.addHandler(console_handler)
    log.addHandler(file_handler)



# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

# pylint: disable=no-value-for-parameter
@click.group(help="CLI tool to manage iNaturalist data import pipeline")
@click.option(
    "--config", "-c", "config_path",
    type=click.Path(exists=True),
    default="config.ini",
    envvar="INAT_CONFIG",
    help="Path to config file."
)
@click.option(
    "-u", "--username", 
    envvar="INAT_USERNAME",
    default=None,
    help="iNaturalist username (overrides config)"
)
@click.option(
    "-d", "--db", "db_file",
    type=click.Path(exists=False),
    envvar="OBSERVATION_DATABASE",
    default=None,
    help="Database file path (overrides config)"
)
@click.pass_context
def main(ctx: click.Context, username: str | None, db_file: str | None, config_path: str | None):
    """
    TODO big long explanation of how this tool works
    """
    logging_setup(logger, "logs", "pipeline.log")

    # Read config file
    try:
        cf = ConfigParser()
        with open(config_path, "r", encoding="latin-1") as fp:
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

    if db_file is not None:
        raw_config["core"]["db_file"] = db_file
    if username is not None:
        raw_config["core"]["username"] = username

    ctx.obj = raw_config

    logger.info("---------------------------------------")
    logger.info("*** iNaturalist Data Pipeline Tool  ***")
    logger.info("---------------------------------------")
    logger.info("File database: %s", raw_config["core"]["db_file"])
    logger.info("iNaturalist username: %s", raw_config["core"]["username"])
    logger.info("")


# ---------------------------------------------------------------------------
# Taxa
# ---------------------------------------------------------------------------

@main.command("taxa")
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
def taxa_command(ctx: click.Context, tracking: str | None, rebuild: bool = False):
    """
    Build a taxon mapping and insert it into the local database.
    """
    logger.info("Building taxon map...")

    # Inject config override
    if tracking is not None:
        ctx.obj["taxa"]["tracking_list"] = tracking

    # Validate configs
    try:
        cfg_core, cfg_taxa = config.validate_config(ctx.obj, "taxa", config.TaxaConfig)
    except ValidationError as ex:
        _exit_failure(ex)

    db_manager = db.DBManager(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)
    db_setup(db_manager)

    # Run
    try:
        pipeline.build_taxon_mapping(cfg_taxa, db_manager, auth, rebuild)
    except ValueError as ex:
        _exit_failure(ex)

    _exit_success()


# ---------------------------------------------------------------------------
# Download Observations
# ---------------------------------------------------------------------------

@main.command("observations")
@click.option(
    "-d", "--days-since-update", "days_since_update",
    default=None,
    help="How many days since a taxon was last searched to update."
)
@click.option(
    "--all", "-a", "download_all",
    is_flag=True,
    help="Search for all observations, not just ones inside the project."
)
@click.option(
    "--max", "-m", "max_observations",
    default=None,
    help="Maximum number of observations to download (overrides config)"
)
@click.pass_context
def observations_command(
    ctx: click.Context,
    days_since_update: Optional[int] = None,
    download_all: bool = False,
    max_observations: int = None
):
    """
    Download observations, identifications, and users into local database.
    """
    # Inject config override
    if days_since_update is not None:
        ctx.obj["observations"]["update_after_days"] = days_since_update
    if download_all:
        ctx.obj["observations"]["project_id"] = None
    if max_observations:
        ctx.obj["observations"]["max_observations"] = max_observations

    # Validate config
    try:
        cfg_core, cfg_obs = config.validate_config(
            ctx.obj, "observations", config.ObservationsConfig
        )
    except ValidationError as ex:
        _exit_failure(ex)

    # Get database and authentication
    db_manager = db.DBManager(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)
    db_setup(db_manager)

    # Run
    try:
        pipeline.get_observations(cfg_obs, db_manager, auth)
    except ValueError as ex:
        _exit_failure(ex)

    _exit_success()


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

@main.command("review")
@click.option("-e", "--export_file", "export_file",
    default=None,
    help="File to export reviewed observations to (will be overwritten)"
)
@click.option(
    "--expert-list", "expert_list",
    default=None,
    help="Experts list file (overrides config value)"
)
@click.pass_context
def review_command(ctx: click.Context, export_file: str, expert_list: str):
    """Export data from database"""
    # Inject config override
    if export_file is not None:
        ctx.obj["review"]["export_csv"] = export_file
    if expert_list:
        ctx.obj["review"]["csv_file"] = expert_list

    # Validate config
    try:
        cfg_core, cfg_review = config.validate_config(ctx.obj, "review", config.ReviewConfig)
    except ValidationError as ex:
        _exit_failure(ex)

    # Get database and authentication
    db_manager = db.DBManager(cfg_core.db_file)
    db_setup(db_manager)

    try:
        pipeline.run_review(cfg_review, db_manager)
    except ValueError as ex:
        _exit_failure(ex)

    _exit_success()



# ---------------------------------------------------------------------------
# Project Members
# ---------------------------------------------------------------------------

@main.command("update-members")
@click.pass_context
def project_members(ctx: click.Context):
    """
    Query for project members and update database table
    """
    # Validate config
    try:
        cfg_core, cfg_obs = config.validate_config(
            ctx.obj, "observations", config.ObservationsConfig
        )
    except ValidationError as ex:
        _exit_failure(ex)

    db_manager = db.DBManager(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)
    db_setup(db_manager)

    try:
        pipeline.update_project_members(cfg_obs, db_manager, auth)
    except ValueError as ex:
        _exit_failure(ex)

    _exit_success()

# ---------------------------------------------------------------------------
# Update Annotations
# ---------------------------------------------------------------------------

@main.command("update-annotations")
@click.pass_context
def update_annotations(ctx: click.Context):
    """
    Load all of iNaturalist's annotation categories and values into the database.
    """
    # Validate config
    try:
        cfg_core, _ = config.validate_config(ctx.obj)
    except ValidationError as ex:
        _exit_failure(ex)

    db_manager = db.DBManager(cfg_core.db_file)
    auth = get_auth(cfg_core.user_agent, cfg_core.username)
    db_setup(db_manager)

    try:
        pipeline.update_annotations(db_manager, auth)
    except ValueError as ex:
        _exit_failure(ex)

    _exit_success()


# ---------------------------------------------------------------------------
# Get Biotics tracking query
# ---------------------------------------------------------------------------

@main.command("biotics-query")
def biotics_query():
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


if __name__ == "__main__":
    main()
