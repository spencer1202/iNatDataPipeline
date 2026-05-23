from configparser import ConfigParser
import requests
import time
import logging
import click

from inatdatapipeline.db_manager import DBManager
from inatdatapipeline.inaturalist_auth import iNaturalistAuth

logger = logging.getLogger('pipeline')


class ProjectMembers:
    def __init__(self, project_id: int, per_page: int): 
        self.project_id = project_id
        self.per_page = per_page
        
    
    def run(self, db_manager: DBManager, auth: iNaturalistAuth):
        """
        Query project members and insert them into the database.
        """
        member_ids = self.fetch_project_members(auth)
        logger.debug(f"Found {len(member_ids)} project members.")

        try:
            with db_manager as db:
                rows_inserted = db_manager.replace_project_members(member_ids)
        except Exception as err:
            logger.error(f"Failed to insert project members into the database.")

        logger.info(f"Inserted {rows_inserted} new member IDs.")


    def fetch_project_members(self, auth: iNaturalistAuth) -> set:
        """
        Get the user IDs of all users in the iNaturalist project.
        Args:
            auth:
                iNaturalist authentication object
        Returns:
            Set of user IDs
        """
        url = f"https://api.inaturalist.org/v2/projects/{self.project_id}/members"
        headers = auth.get_auth_headers()
        params = {
            "per_page": self.per_page
        }

        # Make API requests
        all_results = []
        page = 1
        while True:
            params["page"] = page
            logger.debug(f"Page {page}")
            try:
                response = requests.get(
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                all_results.extend(results)
                time.sleep(0.5)

                if len(results) < self.per_page:
                    break

                page += 1
                time.sleep(0.5)
                
            except requests.Timeout:
                logger.error(f"Request timed out.")
        
        # Extract user IDs from API response
        users = set()
        for result in all_results:
            try:
                user_id = int(result.get("user", {}).get("id"))
                users.add(user_id)
            except:
                logger.error(f"Invalid user ID response: {user_id}")
        return users