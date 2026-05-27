"""
This module contains classes that perform smaller miscelaneous API request tasks, as well as a
request paging helper function.
"""

import requests
import time
import logging
import pandas as pd

logger = logging.getLogger('pipeline')

TIMEOUT = 30


"""
This module handles getting an iNaturalist authentication token.
"""

import getpass
import os
from dotenv import load_dotenv
import keyring
from pyinaturalist import KEYRING_KEY
import pyinaturalist

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_yn_input(msg: str) -> bool:
    """
    Asks the user a yes/no question, validates input, returns result
    """
    result = False
    while True:
        print(msg)
        to_continue = input(msg)
        if to_continue.lower() == "yes" or to_continue.lower() == "y":
            result = True
            break
        if to_continue.lower() == "no" or to_continue.lower() == "n":
            result = False
            break

        print("Invalid input.")

    return result


# ---------------------------------------------------------------------------
# iNaturalist Authentication
# ---------------------------------------------------------------------------
class INaturalistAuth:
    """
    Helper class that handles getting iNaturalist access tokens and request headers.
    """
    def __init__(self, user_agent: str = "iNat_ORBIC_DataPipeline/1.0"):
        self.user_agent: str = user_agent
        self.access_token: str = None

    def generate_access_token(self, user: str) -> str | None:
        """
        Fetches iNaturalist authorization access token using credentials from the system keyring. 
        If not present, prompts the user for credentials and saves them to the system keyring.
        """
        # Try to load app secret and ID from .env file
        if (
            not load_dotenv('.env')
            or not os.environ.get("INAT_APP_ID")
            or not os.environ.get("INAT_APP_SECRET")
        ):
            raise ValueError("App credentials not present in environment file.")

        username = keyring.get_password(KEYRING_KEY, 'username')
        password = keyring.get_password(KEYRING_KEY, 'password')

        # Check if user wants to use current credentials
        if username and password:
            if username == user:
                self.access_token = pyinaturalist.get_access_token()
                return self.access_token
            if get_yn_input(
                f"Found iNaturalist credentials for {username}, not {user}. " +
                "Would you like to proceed with these credentials instead? (Y/N): "
            ):
                self.access_token = pyinaturalist.get_access_token()
                return self.access_token
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
        """Get this object's access token if generated"""
        return self.access_token


    def get_auth_headers(self):
        """Get authentication headers for API requests"""
        if not self.access_token:
            return None

        headers = {}
        headers["User-Agent"] = self.user_agent
        headers["Authorization"] = f"Bearer {self.access_token}"
        return headers


# ---------------------------------------------------------------------------
# Other Request Helpers
# ---------------------------------------------------------------------------

def PageRequests(url: str, params: dict, headers: dict, per_page: int) -> list:
    """
    Helper function for paging through requests. Returns a list of results.
    """
    params["per_page"] = per_page
    all_results = []

    page = 1
    fail_count = 0
    while True:
        params["page"] = page
        try:
            logger.debug(f"\tpage #{page}")
            response = requests.get(
                url=url,
                headers=headers,
                params=params,
                timeout=TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            all_results.extend(results)
            time.sleep(0.5)

            if len(results) < per_page:
                break

            page += 1
            time.sleep(0.5)

        except requests.Timeout:
            fail_count += 1
            logger.error("Request timed out.")
            if fail_count > 5:
                raise requests.exceptions.RequestException("Request timed out too many times.")

        except requests.exceptions.RequestException as ex:
            fail_count += 1
            logger.error(f"Encountered unknown exception: {ex}")
            if fail_count > 5:
                raise requests.exceptions.RequestException("Recieved too many errors.")

    return all_results


def SlidingPageRequests(url: str, params: dict, headers: dict, per_page: int) -> list:
    all_results = []
    has_more = True
    iterations = 0
    while has_more:
        response = requests.get(url, params, headers=headers)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if not results:
            has_more = False
            break
            
        all_results.extend(results)
        iterations += 1

        last_id = results[-1].get("id")
        logger.debug(f"Batch {iterations} fetched. Last ID: {last_id}. Total so far: {len(all_results)}.")

        params["id_above"] = last_id

        time.sleep(1.0)

    return all_results


def FetchProjectMembers(auth: INaturalistAuth, per_page: int, project_id: int) -> set:
    """
    Get the user IDs of all users in the iNaturalist project.
    Args:
        auth:
            iNaturalist authentication object
    Returns:
        Set of user IDs
    """
    url = f"https://api.inaturalist.org/v2/projects/{project_id}/members"
    headers = auth.get_auth_headers()

    # Make API requests
    all_results = PageRequests(url, {}, headers, per_page)
    
    # Extract user IDs from API response
    users = set()
    for result in all_results:
        try:
            user_id = int(result.get("user", {}).get("id"))
            users.add(user_id)
        except:
            logger.error(f"Invalid user ID response: {user_id}")
    return users


def FetchAnnotations(auth: INaturalistAuth) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch all available annotations and annotation values from iNaturalist.
    """
    URL = "https://api.inaturalist.org/v2/controlled_terms?fields=all"
    headers = auth.get_auth_headers()

    try:
        response = requests.get(URL, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as ex:
        logger.error("Encountered unknown request exception: %s" % ex)

    data = response.json()
    results = data.get("results", [])
    
    annotations = []
    values = []
    for result in results:
        annotation_id = result.get("id")
        annotation = {
            "annotation_id": annotation_id,
            "label": result.get("label")
        }
        annotations.append(annotation)

        # Get values for this annotation
        options = result.get("values")
        for option in options:
            value = {
                "value_id": option.get("id"),
                "annotation_id": annotation_id,
                "label": option.get("label")
            }
            values.append(value)
    
    return pd.DataFrame(annotations), pd.DataFrame(values)
