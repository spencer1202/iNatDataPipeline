import os
import logging
import argparse
from configparser import ConfigParser
import click

import taxa
import helpers
from inaturalist_auth import iNaturalistAuth
from db_manager import DBManager
from observations import ObservationQuery

logger = logging.getLogger('pipeline')
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db(config) -> DBManager:
    """
    Set up a database manager object
    """
    try:
        return DBManager(config["DEFAULT"]["db_file"])
    except KeyError as err:
        logger.error("Could not locate database file path in config.")
        raise click.ClickException(err)
    except err:
        logger.error("Failed to connect to file database.")
        raise click.ClickException(err)


def get_auth(config) -> iNaturalistAuth:
    """
    Set up an iNaturalist authentication object
    """
    try:
        auth: iNaturalistAuth = iNaturalistAuth(config["authentication"]["user_agent"])
        auth.generate_access_token(config["authentication"]["username"])
    except KeyError as err:
        logger.error("Could not locate user agent or username in config file.")
        raise click.ClickException(err)
    except Exception as err:
        logger.error("Failed to generate access token.")
        raise click.ClickException(err)
    if not auth.get_access_token():
        logger.error("Could not obtain OAuth2 access token.")
        raise click.ClickException()

    return auth

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
    "--database", "db_file",
    envvar="OBSERVATION_DATABASE",
    default=None,
    help="Database file path (overrides config)"
)
@click.pass_context
def main(ctx: click.Context, username: str | None, database: str | None, config_path: str | None):
    helpers.logging_setup(logger, logging.INFO, logging.DEBUG, "logs", "pipeline.log")

    # Set up click CLI context
    ctx.ensure_object(dict)
    ctx.obj["config"] = helpers.parse_config(config_path)
    ctx.obj["config"]["authentication"]["username"] = username or ctx.obj["config"]["authentication"]["username"]

    db_file = database or ctx.obj["config"]["DEFAULT"]["db_file"]
    logger.info("---------------------------------------")
    logger.info("*** iNaturalist Data Pipeline Tool  ***")
    logger.info("---------------------------------------")
    logger.info(f"File database: {db_file}")
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
# Download Observations
# ---------------------------------------------------------------------------

@main.command("download_observations")
@click.pass_context
def download_observations(ctx: click.Context):
    """
    Download observation data to insert observations, identifications, and users into the local database.
    """
    config = ctx.obj["config"]
    logger.info("Downloading observations...")
    
    db_manager = get_db(config)
    auth = get_auth(config)
    
    observation_querier = ObservationQuery(db_manager, config)
    observation_querier.get_observations(auth)

    _done()


# ---------------------------------------------------------------------------
# Build Taxon Map
# ---------------------------------------------------------------------------

@main.command("build_taxon_map")
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
def build_taxon_map(ctx: click.Context, tracking: str | None, rebuild: bool):
    """
    Build a taxon mapping and insert it into the local database.
    """
    config = ctx.obj["config"]
    logger.info("Building taxon map...")
    tracking_file = tracking or config["taxon_map"]["tracking_list"]
    
    db_manager = get_db(config)
    auth = get_auth(config)
    
    taxon_mapper = taxa.TaxonMappingBuilder(db_manager)

    taxon_mapper.build_mapping(
        tracking_file,
        config["taxon_map"]["name_overrides_file"],
        auth,
        rebuild
    )

    _done()



if __name__ == "__main__":
    main()