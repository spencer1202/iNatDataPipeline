"""
TODO insert description of iNatDataPipeline tool

"""

import os
import logging
from configparser import ConfigParser
import click
from pathlib import Path
from pydantic import BaseModel, Field, FilePath, field_validator, BeforeValidator
from typing import Optional, Annotated


import taxa
import helpers
import config
from project_members import ProjectMembers
from inaturalist_auth import iNaturalistAuth
from db_manager import DBManager
from observations import ObservationQuery

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
        print(f"Failed to load config file: {config_path}")
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
    raw_config.setdefault("experts", {})
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
# Export
# ---------------------------------------------------------------------------

@main.command("export")
@click.pass_context
def export(ctx: click.Context):
    """Export data from local database"""
    logger.info("Export - not implemented yet!")
    _done()


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

    # Fill in and valiate config
    if tracking is not None:
        ctx.obj["taxa"]["tracking_list"] = tracking
    cf = config.get_validated_config(logger, ctx.obj)
    if not cf:
        return

    db_manager = get_db(cf.core.db_file)
    auth = get_auth(cf.core.user_agent, cf.core.username)
    taxon_mapper = taxa.TaxonMappingBuilder(db_manager)

    # Make sure database is set up
    with db_manager as db:
        db.setup_db()

    taxon_mapper.build_mapping(
        cf.taxa.tracking_list,
        cf.taxa.name_overrides_file,
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
    
    # Fill in and valiate config
    if days_since_update is not None:
        # print(f"days_since_update = {days_since_update}")
        ctx.obj["observations"]["update_after_days"] = days_since_update
    cf = config.get_validated_config(logger, ctx.obj)
    if not cf:
        return
    
    db_manager = get_db(cf.core.db_file)
    auth = get_auth(cf.core.user_agent, cf.core.username)
    
    # Make sure database is set up
    with db_manager as db:
        db.setup_db()

    observation_querier = ObservationQuery(db_manager, cf)
    observation_querier.get_observations(auth)

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
    cf = config.get_validated_config(logger, ctx.obj)
    if not cf:
        return
    
    logger.info(f"Updating current members in project: {cf.observations.project_id}")

    querier = ProjectMembers(cf.observations.project_id, cf.observations.per_page)
    db_manager = get_db(cf.core.db_file)
    auth = get_auth(cf.core.user_agent, cf.core.username)
    
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

    cf = config.get_validated_config(logger, ctx.obj)
    if not cf:
        return
    
    db_manager = get_db(cf.core.db_file)
    with db_manager as db:
        db.setup_db()
    
    _done()


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
    
    if expert_list:
        ctx.obj["experts"]["csv_file"] = expert_list
    cf = config.get_validated_config(logger, ctx.obj)
    if not cf:
        return
    
    db_manager = get_db(cf.core.db_file)



if __name__ == "__main__":
    main()

