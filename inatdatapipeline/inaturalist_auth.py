from dotenv import load_dotenv
import keyring
from pyinaturalist import KEYRING_KEY
import pyinaturalist
import getpass
import os

import helpers

class iNaturalistAuth:
    """
    Helper class that handles getting iNaturalist access tokens and request headers.
    """
    def __init__(self, user_agent: str = "iNat_ORBIC_DataPipeline/1.0"):
        self.user_agent: str = user_agent
        self.access_token: str = None

    def generate_access_token(self, user: str) -> str:
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
            if username == user:
                self.access_token = pyinaturalist.get_access_token()
                return
            if helpers.get_yn_input(f"Found iNaturalist credentials for {username}, not {user}. Would you like to proceed with these credentials instead? (Y/N): "):
                self.access_token = pyinaturalist.get_access_token()
                return
        else:
            print("No saved credentials found.")
            
        print("Enter your iNaturalist credentials below.")
        username = input('Username: ')
        password = getpass.getpass()

        pyinaturalist.auth.set_keyring_credentials(
            username    = username,
            password    = password,
            app_id      = os.environ['INAT_APP_ID'],
            app_secret  = os.environ['INAT_APP_SECRET']
        )
        print("Credentials saved to keyring for future use.")
        
        self.access_token = pyinaturalist.get_access_token()
        return self.access_token
        

    def get_access_token(self) -> str:
        return self.access_token


    def get_auth_headers(self):
        """Get authentication headers for API requests"""
        if not self.access_token:
            return None
        
        headers = {}
        headers["User-Agent"] = self.access_token
        headers["Authorization"] = f"Bearer {self.access_token}"
        return headers
