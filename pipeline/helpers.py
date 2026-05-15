import os
import logging
import argparse
from configparser import ConfigParser

def get_yn_input(msg: str) -> bool:
    """
    Asks the user a yes/no question, validates input, returns result
    """
    success = False
    while not success:
        print(msg)
        to_continue = input(msg)
        if to_continue.lower() == "yes" or to_continue.lower() == "y":
            return True
        elif to_continue.lower() == "no" or to_continue.lower() == "n":
            return False
        else:
            print("Invalid input.")


def parse_config(args: argparse.Namespace) -> ConfigParser:
    """
    Parse config file and replace options with arguments where specified.

    Args:
        args: Namespace object from argparser
    Returns:
        ConfigParser object loaded with config options
    """
    try:
        config = ConfigParser()
        config.read(args.config)
    except:
        print(f"Failed to load config file: {args.config}")
        raise

    if args.username:
        config["authentication"]["username"] = args.username
    if args.tracking:
        config["taxon_map"]["tracking_list"] = args.tracking
    if args.database:
        config["DEFAULT"]["db_file"] = args.database

    return config


def logging_setup(logger: logging.Logger, console_level: int, file_level: int, log_folder: str = "logs", log_file: str = "taxon_mapping.log"):
    # Make sure name maps folder exists
    os.makedirs(log_folder, exist_ok=True)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    file_handler = logging.FileHandler(os.path.join(log_folder, log_file))
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M"))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments.
    """
    argparser = argparse.ArgumentParser(
        prog="iNaturalistDataPipeline",
        description="Command line tool for pulling observation data from iNaturalist."
    )
    argparser.add_argument("command",
                           help="[taxa | download | members | export] - which stage of the pipeline you'd like to run.")
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
    argparser.add_argument("-r", "--rebuild_taxa",
                           action="store_true",
                           help="Force rebuild taxon mapping (not recommended)."
    )
    return argparser.parse_args()


