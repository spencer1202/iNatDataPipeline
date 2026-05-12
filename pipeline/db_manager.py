import sqlite3
import pandas as pd
from contextlib import closing

class DBManager:
    def __init__(self, db_file: str):
        self._conn          : sqlite3.Connection = None
        self.db_file        : str = db_file


    def __enter__(self):
        self.connect()
        return self
    

    def __exit__(self, exc_type, exc_value, traceback):
        self.commit()
        self.close()


    def connect(self):
        """
        Connect to sqlite database. Connection stored in self._conn. Closes previous connection if one was open.
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
                est_id                int     NOT NULL REFERENCES tracking_taxa(est_id),
                exact_match           boolean CHECK (exact_match IN (NULL, true, false)),
                PRIMARY KEY(taxon_id, est_id)
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
                captive_cultivated    boolean CHECK (captive_cultivated IN (NULL, true, false)),
                obscured              boolean CHECK (obscured IN (NULL, true, false))
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
            """
            CREATE VIEW IF NOT EXISTS mapping (
                est_id, 
                elcode, 
                sname, 
                scomname, 
                taxon_id, 
                inat_name, 
                exact_match
            ) AS SELECT (
                tt.est_id, 
                tt.elcode, 
                tt.sname, 
                tt.scomname, 
                it.taxon_id, 
                it.inat_name, 
                tr.exact_match
            )
            FROM tracking_taxa AS tt
            JOIN tracking_rel AS tr ON tt.est_id = tr.est_id
            JOIN inat_taxa AS it ON tr.taxon_id = it.taxon_id;
            """,
            """
            CREATE VIEW IF NOT EXISTS not_in_inat 
            AS SELECT * 
            FROM tracking_taxa AS tt
            LEFT JOIN tracking_rel AS tr
            ON tt.est_id = tr.est_id
            WHERE tr.est_id IS NULL;
            """
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


    def insert_mappings(self, mapping_df: pd.DataFrame):
        """
        Inserts new taxon mappings into the database
        """
        statements = [
            """
            INSERT OR IGNORE INTO tracking_taxa (est_id, elcode, sname, scomname)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(est_id) 
            DO UPDATE SET 
                elcode = excluded.elcode,
                sname = excluded.sname,
                scomname = excluded.scomname;
            """,
            """
            INSERT OR IGNORE INTO inat_taxa (taxon_id, inat_name)
            VALUES (?, ?)
            ON CONFLICT(taxon_id) 
            DO UPDATE SET 
                inat_name = excluded.inat_name;
            """,
            """
            INSERT OR IGNORE INTO tracking_rel (taxon_id, est_id, exact_match)
            VALUES (?, ?, ?);
            """
        ]
        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(
                statements[0],
                list(mapping_df[["est_id", "elcode", "sname", "scomname"]].itertuples(index=False))
            )
            cursor.executemany(
                statements[1],
                list(mapping_df[["taxon_id", "inat_name"]].itertuples(index=False))
            )
            cursor.executemany(
                statements[2],
                list(mapping_df[["taxon_id", "est_id", "exact_match"]].itertuples(index=False))
            )


    def update_tracking(self, tracking_df: pd.DataFrame):
        """
        Updates database tracking list with the records in tracking_df. 
        Tracking dataframe must have columns [est_id, elcode, sname, scomname]
        """
        
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
        self.check_connection()

        cols = ["est_id", "elcode", "sname", "scomname"]
        tracking_df[cols].to_sql("temp_tracking", self._conn, if_exists="replace")
        with closing(self._conn.cursor()) as cursor:
            cursor.execute(statement)
            cursor.execute("DROP TABLE IF EXISTS temp_tracking")

        self.commit()


    def insert_overrides(self, overrides_df: pd.DataFrame):
        """
        Insert name overrides into database

        Returns:
            Number of records updated
        """
        statement = """
        UPDATE tracking_taxa
        SET clean_name = temp.inat_name
        FROM temp_overrides AS temp
        WHERE temp.est_id = tracking_taxa.est_id
        """
        self.check_connection()

        overrides_df.to_sql("temp_overrides", self._conn, if_exists="replace")
        with closing(self._conn.cursor()) as cursor:
            cursor.execute(statement)
            count = cursor.rowcount
            cursor.execute("DROP TABLE IF EXISTS temp_overrides")

        self.commit()
        return count


    def get_mappings(self) -> pd.DataFrame:
        """
        Queries the iNat database for taxon mappings
        """
        query = """
        SELECT 
            tt.est_id       AS est_id,
            tt.elcode       AS elcode,
            tt.sname        AS sname,
            tt.scomname     AS scomname,
            it.taxon_id     AS taxon_id,
            it.inat_name    AS inat_name
        FROM tracking_taxa AS tt
        JOIN tracking_rel AS tr
            ON tt.est_id = tr.est_id
        JOIN inat_taxa AS it
            ON tr.taxon_id = it.taxon_id;
        """
        self.check_connection()

        with closing(self._conn.cursor()) as cursor:
            result = cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            df = pd.DataFrame(
                result.fetchall(),
                columns=columns
            )
        return df

        
    

    def __del__(self):
        if self._conn:
            self._conn.close()
