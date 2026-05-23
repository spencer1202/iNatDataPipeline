import sqlite3
import pandas as pd
from contextlib import closing
import datetime as dt
import re
import click


create_statements = {
    "tracking_taxa":
        """
        CREATE TABLE IF NOT EXISTS tracking_taxa (
            est_id                int     NOT NULL PRIMARY KEY,
            sci_name              text,
            element_type          text,
            scientific_name       text,
            common_name           text,
            element_name          text,
            family                text,
            author                text,
            egt_uid               int     NOT NULL,
            srank                 text,
            track_status          text,
            explorer              text,
            explorer_link         text,
            elcode                text    NOT NULL,
            growth_habit          text,
            duration              text
        );
        """,
    "inat_taxa":        
        """
        CREATE TABLE IF NOT EXISTS inat_taxa (
            taxon_id              int     PRIMARY KEY NOT NULL,
            inat_name             text,
            date_updated          text
        );
        """,
    "tracking_rel":
        """
        CREATE TABLE IF NOT EXISTS tracking_rel (
            taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id),
            est_id                int     NOT NULL REFERENCES tracking_taxa(est_id),
            exact_match           boolean CHECK (exact_match IN (NULL, true, false)),
            PRIMARY KEY(taxon_id, est_id)
        );
        """,
    "users":
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id               int     PRIMARY KEY NOT NULL,
            login                 text,
            name                  text
        );
        """,
    "observations":
        """
        CREATE TABLE IF NOT EXISTS observations (
            observation_id              int     PRIMARY KEY NOT NULL,
            observer_id                 int     NOT NULL REFERENCES users(user_id),
            taxon_id                    int     NOT NULL REFERENCES inat_taxa(taxon_id),
            license                     text,
            latitude                    float,
            longitude                   float,
            latitude_private            float,
            longitude_private           float,
            coordinate_precision        float,
            coordinate_precision_public float,
            observed_on                 text,
            observed_on_string          text,
            created_at                  text,
            updated_at                  text,
            quality_grade               text,
            url                         text,
            description                 text,
            id_agreements               int,
            id_disagreements            int,
            place_guess                 text,
            place_guess_private         text,
            captive_cultivated          boolean CHECK (captive_cultivated IN (NULL, true, false)),
            obscured                    boolean CHECK (obscured IN (NULL, true, false)),
            in_project                  boolean CHECK (in_project IN (NULL, true, false))
        );
        """,
    "experts":
        """
        CREATE TABLE IF NOT EXISTS experts (
            user_id               int     PRIMARY KEY,
            expertise             text
        );
        """,
    "identifications":
        """
        CREATE TABLE IF NOT EXISTS identifications (
            identification_id     int     PRIMARY KEY NOT NULL,
            observation_id        int     NOT NULL REFERENCES observations(observation_id),
            user_id               int     NOT NULL REFERENCES users(user_id),
            taxon_id              int     NOT NULL REFERENCES inat_taxa(taxon_id),
            created_at            text
        );
        """,
    "mapping":
        """
        CREATE VIEW IF NOT EXISTS mapping (
            est_id, 
            elcode, 
            scientific_name, 
            common_name, 
            taxon_id, 
            inat_name, 
            exact_match
        ) AS SELECT 
            tt.est_id, 
            tt.elcode, 
            tt.scientific_name, 
            tt.common_name, 
            it.taxon_id, 
            it.inat_name, 
            tr.exact_match
        FROM tracking_taxa AS tt
        JOIN tracking_rel AS tr ON tt.est_id = tr.est_id
        JOIN inat_taxa AS it ON tr.taxon_id = it.taxon_id;
        """,
    "project_members":
        """
        CREATE TABLE IF NOT EXISTS project_members (
            user_id int PRIMARY KEY NOT NULL
        );
        """,
    "not_in_inat":
        """
        CREATE VIEW IF NOT EXISTS not_in_inat 
        AS SELECT * 
        FROM tracking_taxa AS tt
        LEFT JOIN tracking_rel AS tr
        ON tt.est_id = tr.est_id
        WHERE tr.est_id IS NULL;
        """,
    "tracking_trigger": 
        """
        CREATE TRIGGER IF NOT EXISTS fk_cascade_delete_tracking
        AFTER DELETE ON inat_taxa
        BEGIN
            DELETE FROM tracking_rel WHERE taxon_id = OLD.taxon_id;
        END;
        """,
    "expert_identifications":
        """
        CREATE VIEW IF NOT EXISTS expert_identifications (
            identification_id,
            observation_id,
            user_id,
            name,
            login,
            taxon_id,
            created_at,
            est_id,
            elcode,
            expertise
        )
        AS SELECT
            id.identification_id,
            id.observation_id,
            id.user_id,
            us.login,
            us.name,
            id.taxon_id,
            id.created_at,
            tr.est_id,
            tr.elcode,
            ex.expertise
        FROM identifications AS id
        LEFT JOIN tracking_rel 
            ON id.taxon_id = tracking_rel.taxon_id
        LEFT JOIN tracking_taxa AS tr 
            ON tracking_rel.est_id = tr.est_id
        JOIN experts AS ex 
            ON id.user_id = ex.user_id
        JOIN users AS us
            ON id.user_id = us.user_id;
        """,
    "full_observations":
        """
        CREATE VIEW IF NOT EXISTS full_observations
        AS SELECT *
        FROM observations obs
        JOIN tracking_rel tr
            ON obs.taxon_id = tr.taxon_id
        JOIN tracking_taxa tt
            ON tr.est_id = tt.est_id;
        """
}


class DBManager:
    def __init__(self, db_file: str):
        self._conn   : sqlite3.Connection = None
        self.db_file : str = db_file


    def __enter__(self):
        """
        Called when entering a "with" clause. Opens connection to database.
        """
        self.connect()
        return self
    

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Called when exiting a "with" clause. Commits database transaction and closes connection.
        """
        self.commit()
        self.close()

    
    def __del__(self):
        if self._conn:
            self._conn.close()

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
        
        try:
            with closing(self._conn.cursor()) as cursor:
                for _, statement in create_statements.items():
                    cursor.execute(statement)
        except:
            print("Error while creating database tables.")
            raise
        

    def commit(self):
        """
        Commits database transaction
        """
        self.check_connection()
    
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
            INSERT OR IGNORE INTO tracking_taxa (
                sci_name,
                est_id, 
                element_type,
                scientific_name, 
                common_name,
                element_name,
                family,
                author,
                egt_uid,
                srank,
                track_status,
                explorer,
                explorer_link,
                elcode, 
                growth_habit,
                duration
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(est_id) 
            DO UPDATE SET
                sci_name = excluded.sci_name, 
                element_type = excluded.element_type,
                scientific_name = excluded.scientific_name,
                common_name = excluded.common_name,
                element_name = excluded.element_name,
                family = excluded.family,
                author = excluded.author,
                egt_uid = excluded.egt_uid,
                srank = excluded.srank,
                track_status = excluded.track_status,
                explorer = excluded.explorer,
                explorer_link = excluded.explorer_link,
                elcode = excluded.elcode,
                growth_habit = excluded.growth_habit,
                duration = excluded.duration
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
        tracking_cols = [
            "sci_name", 
            "est_id", 
            "element_type", 
            "scientific_name", 
            "common_name", 
            "element_name",
            "family",
            "author",
            "egt_uid",
            "srank",
            "track_status",
            "explorer",
            "explorer_link",
            "elcode",
            "growth_habit",
            "duration"
        ]
        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(
                statements[0],
                list(mapping_df[tracking_cols].itertuples(index=False))
            )
            cursor.executemany(
                statements[1],
                list(mapping_df[["taxon_id", "inat_name"]].itertuples(index=False))
            )
            cursor.executemany(
                statements[2],
                list(mapping_df[["taxon_id", "est_id", "exact_match"]].itertuples(index=False))
            )


    def _select_query(self, query) -> pd.DataFrame:
        """
        Helper function for doing a simple select query and putting the results in a dataframe
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


    def get_mappings(self) -> pd.DataFrame:
        """
        Queries the iNat database for taxon mappings
        """
        return self._select_query("SELECT * FROM mapping")

    
    def get_inat_taxa(self) -> pd.DataFrame:
        """
        Queries database for iNaturalist taxa
        """
        df = self._select_query("SELECT * FROM inat_taxa")
        df["date_updated"] = df["date_updated"]
        return df

    
    def replace_project_members(self, member_ids: set[int]):
        """
        Replace project_members table with new entries
        """
        insert_statement =  """
                            INSERT OR IGNORE INTO project_members (user_id)
                            VALUES (?);
                            """

        self.check_connection()

        with closing(self._conn.cursor()) as cursor:
            ids = [(id,) for id in member_ids]
            cursor.execute("DROP TABLE IF EXISTS project_members;")
            cursor.execute(create_statements["project_members"])
            cursor.executemany(insert_statement, ids)
            count = cursor.rowcount
        
        return count


    def insert_users(self, users: list):
        """
        Inserts new users into users table
        """
        statement = """
        INSERT INTO users (user_id, login, name)
        VALUES (:id, :login, :name)
        ON CONFLICT (user_id)
        DO UPDATE SET 
            login = login,
            name = name;
        """
        self.check_connection()

        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(statement, users)
            count = cursor.rowcount
        return count


    def insert_observations(self, observations: list[dict]) -> int:
        """
        Inserts new observations into users table
        """
        statement = """
        INSERT INTO observations (
            observation_id,
            observer_id,
            taxon_id,
            license,
            latitude,
            longitude,
            latitude_private,
            longitude_private,
            coordinate_precision,
            coordinate_precision_public,
            observed_on,
            observed_on_string,
            created_at,
            updated_at,
            quality_grade,
            url,
            description,
            id_agreements,
            id_disagreements,
            place_guess,
            place_guess_private,
            captive_cultivated,
            obscured,
            in_project
        )
        VALUES (
            :observation_id,
            :observer_id,
            :taxon_id,
            :license,
            :latitude,
            :longitude,
            :latitude_private,
            :longitude_private,
            :coordinate_precision,
            :coordinate_precision_public,
            :observed_on,
            :observed_on_string,
            :created_at,
            :updated_at,
            :quality_grade,
            :url,
            :description,
            :id_agreements,
            :id_disagreements,
            :place_guess,
            :place_guess_private,
            :captive_cultivated,
            :obscured,
            :in_project
        )
        ON CONFLICT (observation_id)
        DO UPDATE SET
            observer_id = excluded.observer_id,
            taxon_id = excluded.taxon_id,
            license = excluded.license,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            latitude_private = excluded.latitude_private,
            longitude_private = excluded.longitude_private,
            coordinate_precision = excluded.coordinate_precision,
            coordinate_precision_public = excluded.coordinate_precision_public,
            observed_on = excluded.observed_on,
            observed_on_string = excluded.observed_on_string,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            quality_grade = excluded.quality_grade,
            url = excluded.url,
            description = excluded.description,
            id_agreements = excluded.id_agreements,
            id_disagreements = excluded.id_disagreements,
            place_guess = excluded.place_guess,
            place_guess_private = excluded.place_guess_private,
            captive_cultivated = excluded.captive_cultivated,
            obscured = excluded.obscured,
            in_project = excluded.in_project
        """
        self.check_connection()

        # count = df.to_sql("temp_observations", self._conn, if_exists="replace")
        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(statement, observations)
            count = cursor.rowcount

        return count


    def insert_identifications(self, identifications: list[dict]):
        statement = """
        INSERT INTO identifications (
            identification_id,
            observation_id,
            user_id,
            taxon_id,
            created_at
        )
        VALUES ( 
            :identification_id,
            :observation_id,
            :user_id,
            :taxon_id,
            :created_at
        )
        ON CONFLICT (identification_id)
        DO UPDATE SET
            identification_id = excluded.identification_id,
            observation_id = excluded.observation_id,
            user_id = excluded.user_id,
            taxon_id = excluded.taxon_id,
            created_at = excluded.created_at
        """
        self.check_connection()

        with closing(self._conn.cursor()) as cursor:
            cursor.executemany(statement, identifications)
            count = cursor.rowcount
        
        return count
    

    def update_checked_date(self, complete_taxa: set):
        placeholders = ', '.join(['?'] * len(complete_taxa))
        statement = f"""
        UPDATE inat_taxa
        SET date_updated = ?
        WHERE taxon_id IN ({placeholders})
        """
        self.check_connection()
        
        with closing(self._conn.cursor()) as cursor:
            cursor.execute(statement, [dt.date.today()] + list(complete_taxa))


    def get_expert_identifications(self):
        """
        Get identifications made by experts whose expertise matches the taxon.
        """
        self.check_connection()
        self._conn.create_function("REGEXP_MATCH", 2, DBManager.match_wildcards)
        self._conn.execute(create_statements["expert_identifications"])

        query = """
        SELECT * FROM expert_identifications
        WHERE REGEXP_MATCH(elcode, expertise) = 1;
        """

        return self._select_query(query)


    def get_full_observations(self):
        """
        Get observations from database
        """
        query = "SELECT * FROM full_observations;"
        self.check_connection()
        return self._select_query(query)
    

    def update_experts(self, df: pd.DataFrame):
        """
        Update the experts table using the given dataframe.
        """
        self.check_connection()
        statement = """
        INSERT INTO experts (user_id, expertise)
        VALUES (?, ?);
        """
        
        try:
            tuples = list(df[["iNaturalist_id", "Expertise LU"]].itertuples(index=False))

        except KeyError as err:
            raise click.ClickException(f"Experts dataframe does not contain the required columns:\n{err}")

        with closing(self._conn.cursor()) as cursor:
            cursor.execute("DROP TABLE IF EXISTS experts")
            cursor.execute(create_statements["experts"])
            cursor.executemany(statement, tuples)
            count = cursor.rowcount

        return count

    @staticmethod
    def match_wildcards(elcode, pattern_string):
        """
        Converts SQL wildcards (A%|I%) into a corresponding regex pattern and checks if the elcode matches.
        """
        try:
            if not elcode or not pattern_string:
                return 0
            
            elcode_str = str(elcode).strip()
            pattern_str = str(pattern_string).strip()
        
            if not elcode_str or not pattern_str:
                return 0

            patterns = pattern_string.split('|')
            regex_parts = []

            for p in patterns:
                safe_p = p.replace(r"%", ".*")
                regex_parts.append(safe_p)

            combined_regex = f"^({"|".join(regex_parts)})$"
            return 1 if re.match(combined_regex, elcode) else 0

        except:
            print(f"\n ---  Crash detected ---")
            print(f"Inputs causing crash: elcode={repr(elcode)}, pattern={repr(pattern_string)}")
            print(f"--------------------------")
            raise