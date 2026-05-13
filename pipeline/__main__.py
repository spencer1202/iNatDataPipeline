import os
import logging
import argparse
from configparser import ConfigParser

import taxa
import helpers
from helpers import iNaturalistAuth
from db_manager import DBManager
from observations import ObservationQuery

logger = logging.getLogger('pipeline')
logger.setLevel(logging.INFO)

def logging_setup(log_folder: str = "logs", log_file: str = "taxon_mapping.log"):
    # Make sure name maps folder exists
    os.makedirs(log_folder, exist_ok=True)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    file_handler = logging.FileHandler(os.path.join(log_folder, log_file))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M"))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments.
    """
    argparser = argparse.ArgumentParser(
        prog="iNaturalistTaxonMappings",
        description="Inserts tracking list into the database, queries iNaturalist for matching taxonomies, and adds" \
                    "taxon mapping to the database."
    )
    argparser.add_argument("-c", "--config", 
                           help="Specify config file.",
                           default="config.ini"
    )
    argparser.add_argument("-u", "--username", 
                           help="iNaturalist username (overrides config)."
    )
    argparser.add_argument("-t", "--tracking",
                           help="Specify tracking list file (overrides config)."
    )
    argparser.add_argument("-d", "--database",
                           help="Specify database file (overrides config)"
    )
    argparser.add_argument("-r", "--rebuild",
                           action="store_true",
                           help="Force rebuild taxon mapping (not recommended)."
    )
    return argparser.parse_args()


def parse_config(args: argparse.Namespace) -> ConfigParser:
    """
    Parse config file and replace options with arguments where specified.

    Args:
        args: Namespace object from argparser
    Returns:
        ConfigParser object loaded with config options
    """
    config = helpers.load_config(args.config)

    if args.username:
        config["authentication"]["username"] = args.username
    if args.tracking:
        config["taxon_map"]["tracking_list"] = args.tracking
    if args.database:
        config["DEFAULT"]["db_file"] = args.database

    return config


def main():
    logging_setup()
    args = parse_args()
    config = parse_config(args)

    auth: iNaturalistAuth = iNaturalistAuth(config["authentication"]["user_agent"])
    auth.generate_access_token(config["authentication"]["username"])
    if not auth.get_access_token():
        logger.error("Could not obtain OAuth2 access token")
        return

    logger.info(f"Connecting to database: {config["DEFAULT"]["db_file"]}.")
    db_manager = DBManager(config["DEFAULT"]["db_file"])
    taxon_mapper = taxa.TaxonMappingBuilder(db_manager)
    
    taxon_mapper.build_mapping(
        # TODO add error checking for non-existent file
        config["taxon_map"]["tracking_list"],
        config["taxon_map"]["name_overrides_file"],
        auth,
        args.rebuild
    )



    observation_querier = ObservationQuery(db_manager, config)



if __name__ == "__main__":
    main()