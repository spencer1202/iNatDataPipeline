from dotenv import load_dotenv
import getpass
import keyring
import os
from configparser import ConfigParser

from pyinaturalist.constants import KEYRING_KEY
import pyinaturalist


def get_access_token() -> str:
    """
    Get iNaturalist authorization access token.
    Fetches credentials from system keyring. If not present, prompts user for credentials and saves them to system keyring.
    """
    # Try to load app secret and ID from .env file
    if not load_dotenv('.env') or not os.environ.get("INAT_APP_ID") or not os.environ.get("INAT_APP_SECRET"):
        raise Exception("App credentials not present in environment file.")

    username = keyring.get_password(KEYRING_KEY, 'username')
    password = keyring.get_password(KEYRING_KEY, 'password')

    # Check if user wants to use current credentials
    if username and password:
        print(f"Found iNaturalist credentials for {username}. Is this correct?")
        success = False
        while not success:
            use_creds = input("(Y/N): ")
            if use_creds.lower() == "yes" or use_creds.lower() == "y":
                return pyinaturalist.get_access_token()
            elif use_creds.lower() == "no" and use_creds.lower() == "n":
                success = True
            else:
                print("Input not recognized.")

    print("No saved credentials found. Enter your iNaturalist credentials below.")
    username = input('Username: ')
    password = getpass.getpass()

    pyinaturalist.auth.set_keyring_credentials(
        username    = username,
        password    = password,
        app_id      = os.environ['INAT_APP_ID'],
        app_secret  = os.environ['INAT_APP_SECRET']
    )
    print("Credentials saved to keyring for future use.")
    
    return pyinaturalist.get_access_token()


def get_auth_headers(api_token: str, user_agent: str = "iNat-TaxonCache/1.0"):
    """Get authentication headers for API requests"""
    headers = {}
    headers["User-Agent"] = user_agent
    headers["Authorization"] = f"Bearer {api_token}"
    return headers



def load_config(config_file: str) -> ConfigParser:
    """Load configuration object from file"""
    try:
        config = ConfigParser()
        config.read(config_file)
        return config
    except:
        print(f"Failed to load config file: {config_file}")
        raise

    # TODO validate config