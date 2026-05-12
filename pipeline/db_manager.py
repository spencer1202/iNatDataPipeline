import sqlite3
import pandas as pd
from contextlib import closing

class DBManager:
    def __init__(self, db_file: str):
        self._conn          : sqlite3.Connection = None
        self.db_file        : str = db_file


    def connect(self):
        """
        Connect to sqlite database. Connection stored in self.db_connection. Closes previous connection if one was open.
        """
        if self._conn:
            self._conn.close()

        try:
            self._conn = sqlite3.connect(self.db_file)
        except sqlite3.Error as err:
            print("Error connecting to database:", err)
            raise
    

    def setup_db(self):
        """
        Sets up the iNat database if by creating tables if they don't already exist. Automatically commits transaction.
        """
        self.check_connection()
        
        statements = [
            """
            CREATE TABLE IF NOT EXISTS tracking_taxa (
                est_id                int     NOT NULL PRIMARY KEY,
                elcode                text    NOT NULL,
                sname                 text,
                override_name         text,
                scomname              text
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS inat_taxa (
                taxon_id              int     PRIMARY KEY,
                inat_name             text
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS tracking_rel (
                taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id),
                est_id                int     NOT NULL REFERENCES tracking_taxa(est_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id               int     PRIMARY KEY,
                login                 text,
                name                  text
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS observations (
                observation_id        int     PRIMARY KEY,
                observer_id           int     NOT NULL REFERENCES users(user_id),
                taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id),
                license               text,
                latitude              float,
                longitude             float,
                coordinate_precision  float,
                observed_on           text,
                created_at            text,
                quality_grade         text,
                url                   text,
                description           text,
                id_agreements         int,
                id_disagreements      int,
                place_guess           text,
                captive_cultivated    boolean NOT NULL CHECK (obscured IN (true, false)),
                obscured              boolean NOT NULL CHECK (obscured IN (true, false))
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS experts (
                user_id               int     PRIMARY KEY REFERENCES users(user_id),
                expertise             text
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS identifications (
                identification_id     int     PRIMARY KEY,
                observation_id        int     NOT NULL REFERENCES observations(observation_id),
                user_id               int     NOT NULL REFERENCES users(user_id),
                taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id)
            );
            """,
        ]

        try:
            with closing(self._conn.cursor()) as cursor:
                for statement in statements:
                    cursor.execute(statement)
        except:
            print("Error while creating database tables.")
            raise
        
        self.commit()


    def commit(self):
        """
        Commits database transaction
        """
        if not self._conn:
            raise ValueError("Must be connected to a database")
    
        self._conn.commit()
    

    def close(self):
        """
        Closes database connection
        """
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def check_connection(self):
        if not self._conn:
            raise ValueError("Must be connected to a database")


    def update_tracking(self, tracking_df: pd.DataFrame):
        """
        Updates database tracking list with the records in tracking_df. 
        Tracking dataframe must have columns [est_id, elcode, sname, scomname]
        """
        self.check_connection()
    
        tracking_df.to_sql("temp_tracking", self._conn, if_exists="replace")
        with closing(self._conn.cursor()) as cursor:
            statement = """
            INSERT INTO tracking_taxa (est_id, elcode, sname, scomname)
            SELECT 
                temp.est_id, 
                temp.elcode, 
                temp.sname, 
                temp.scomname
            FROM temp_tracking AS temp
            WHERE temp.est_id = temp.est_id
            ON CONFLICT (est_id)
            DO UPDATE SET 
                elcode = excluded.elcode,
                sname = excluded.sname,
                scomname = excluded.scomname
            
            """
            cursor.execute(statement)
            cursor.execute("DROP TABLE IF EXISTS temp_tracking")
        self.commit()

    def insert_overrides(self, overrides_df: pd.DataFrame):
        """
        Insert name overrides into database
        """
        self.check_connection()
        overrides_df.to_sql("temp_overrides", self._conn, if_exists="replace")
        statement = """
        UPDATE tracking_taxa
        SET override_name = temp.inat_name
        FROM temp_overrides AS temp
        WHERE temp.est_id = tracking_taxa.est_id
        """



    

    def __del__(self):
        if self._conn:
            self._conn.close()
