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
        config = ConfigParser()
        config.read(config_path)
        return config
    
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
    type=click.Path,
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
    type=click.Path,
    envvar="OBSERVATION_DATABASE",
    default=None,
    help="Database file path (overrides config)"
)
@click.pass_context
def main(ctx: click.Context, username: str | None, db: str | None, config_path: str | None):
    helpers.logging_setup(logger, "logs", "pipeline.log")

    # Read config file
    try:
        config = ConfigParser()
        config.read(config_path)
    except Exception as err:
        print(f"Failed to load config file: {config_path}")
        raise click.ClickException(err)
    
    # Set up click CLI context
    raw_config = {section: dict(config[section]) for section in config.sections()}
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


def get_validated_config(raw_config: dict) -> config.Config:
    try:
        return config.Config(**raw_config)
    except Exception as ex:
        raise click.ClickException(f"Invalid configuration settings:\n{ex}")
    

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
    config = get_validated_config(ctx.obj)
    
    db_manager = get_db(config.core.db_file)
    auth = get_auth(config.core.user_agent, config.core.username)
    taxon_mapper = taxa.TaxonMappingBuilder(db_manager)

    taxon_mapper.build_mapping(
        config.taxa.tracking_list,
        config.taxa.name_overrides_file,
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
        ctx.obj["observations"]["update_before_days"] = days_since_update
    config = get_validated_config(ctx.obj)
    
    db_manager = get_db(config.core.db_file)
    auth = get_auth(config.core.user_agent, config.core.username)
    
    observation_querier = ObservationQuery(db_manager, config)
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
    config = get_validated_config(ctx.obj)

    logger.info(f"Updating current members in project: {config.observations.project_id}")

    querier = ProjectMembers(config.observations.per_page, config.observations.project_id)
    db_manager = get_db(config.core.db_file)
    auth = get_auth(config.core.user_agent, config.core.username)

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

    config = get_validated_config(ctx.obj)

    db_manager = get_db(config.core.db_file)
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
    config = get_validated_config(ctx.obj)

    db_manager = get_db(config.core.db_file)



if __name__ == "__main__":
    main()

