import os
import logging
import click
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
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M"))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

