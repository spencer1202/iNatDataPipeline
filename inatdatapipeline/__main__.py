import os
import logging
import argparse
from configparser import ConfigParser

import taxa
import helpers
from inaturalist_auth import iNaturalistAuth
from db_manager import DBManager
from observations import ObservationQuery

logger = logging.getLogger('pipeline')
logger.setLevel(logging.INFO)


class iNatDataPipeline:
    def __init__(self, args: argparse.Namespace, config: ConfigParser):
        self.args = args
        self.config = config

    def run(self):
        """
        Run the iNaturalist Data Pipeline tool using the command specified in args.command.
        """
        logger.info("---------------------------------------")
        logger.info("*** iNaturalist Data Pipeline Tool  ***")
        logger.info("---------------------------------------")
        logger.info(f"File database: {self.config["DEFAULT"]["db_file"]}")
        
        db_manager = DBManager(self.config["DEFAULT"]["db_file"])
        logger.info("")

        match str(self.args.command).lower():
            case "taxa":
                logger.info("Building taxon map...")
                self.build_taxa_map(db_manager)

            case "download":
                logger.info("Downloading observations...")
                self.get_observation_data(db_manager)

            case "export":
                logger.info("Not implemented yet!")

            case _:
                logger.error("Invalid command. Run \'python pipeline -h\' to see options.")
                return
            
        logger.info("")
        logger.info("Done!")
        logger.info("----------------------------------\n")


    def build_taxa_map(self, db_manager: DBManager):
        """
        Build a taxon mapping and insert it into the local database.
        """
        auth: iNaturalistAuth = iNaturalistAuth(self.config["authentication"]["user_agent"])
        auth.generate_access_token(self.config["authentication"]["username"])
        if not auth.get_access_token():
            logger.error("Could not obtain OAuth2 access token")
            return
        
        taxon_mapper = taxa.TaxonMappingBuilder(db_manager)
    
        taxon_mapper.build_mapping(
            self.config["taxon_map"]["tracking_list"],
            self.config["taxon_map"]["name_overrides_file"],
            auth,
            self.args.rebuild_taxa
        )
    

    def get_observation_data(self, db_manager: DBManager):
        """
        Download observation data to insert observations, identifications, and users into the local database.
        """
        auth: iNaturalistAuth = iNaturalistAuth(self.config["authentication"]["user_agent"])
        auth.generate_access_token(self.config["authentication"]["username"])
        if not auth.get_access_token():
            logger.error("Could not obtain OAuth2 access token")
            return
        
        observation_querier = ObservationQuery(db_manager, self.config)
        observation_querier.get_observations(auth)



def main():
    helpers.logging_setup(logger, logging.INFO, logging.DEBUG, "logs", "pipeline.log")
    args = helpers.parse_args()
    config = helpers.parse_config(args)

    pipeline = iNatDataPipeline(args, config)
    pipeline.run()


if __name__ == "__main__":
    main()