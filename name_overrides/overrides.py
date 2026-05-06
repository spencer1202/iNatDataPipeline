"""
iNaturalist Scientific Name Override Cleaning Script

Cleans data from iNaturalist Collector Species Lists to make them usable for overriding 
scientific names in the taxon mapping.
"""
import pandas as pd
import numpy
import argparse
from configparser import ConfigParser

def fill_elcodes(df: pd.DataFrame, elcodes_df: pd.DataFrame) -> pd.DataFrame:
    """
    Fill in the missing ELCODES from the iNaturalist Collector Species Lists with values from
    Biotics query.
    """
    elcodes_sname_index_df = elcodes_df[["ELCODE", "SNAME", "SCOMNAME"]].set_index("SNAME")
    return df.set_index("SNAME").combine_first(elcodes_sname_index_df).reset_index()


def biotics_query(df: pd.DataFrame) -> str:
    table = "BCD_ET"
    query = f"SELECT * FROM {table} WHERE SNAME IN (\n"
    for _, row in df[df["ELCODE"].isna()].iterrows():
        line = '\'' + row["SNAME"] + "\',\n"
        query += line
    query = query.rstrip(',\n')
    query += "\n)"
    return query


def main():
    # Parse arguments
    argparser = argparse.ArgumentParser(
        prog="iNaturalistNameOverridesGenerator",
        description="Cleans data from iNaturalist Collector Species Lists to make them usable for " \
                    "overriding scientific names in the taxon mapping."
    )
    argparser.add_argument('-f', '--fill', 
                           action='store_true', 
                           help="Use the Biotics query result specified in the config file to fill in missing ELCODEs."
    )
    argparser.add_argument('-q', '--query',
                           action="store_true",
                           help="Write a Biotics query for species with a missing ELCODE, do not create new overrides file.")
    args = argparser.parse_args()

    # Load config file
    config = ConfigParser()
    config.read("config.ini")

    invert_df   = pd.read_csv(config["overrides"]["invertebrates_csv"])
    vert_df     = pd.read_csv(config["overrides"]["vertebrates_csv"])
    vasc_df     = pd.read_csv(config["overrides"]["vascular_csv"])
    nonvasc_df  = pd.read_csv(config["overrides"]["nonvascular_fungi_csv"])
    tracking_df = pd.read_csv(config["taxon_map"]["tracking_list"])

    dfs = [invert_df, vert_df, vasc_df, nonvasc_df]
    cols_to_keep = ["ELCODE", "SNAME", "SCOMNAME", "iNat_name"]
    overrides_df = pd.DataFrame(columns=cols_to_keep)

    for df in dfs:
        df = df.rename(columns={"iNaturalist name if different": "iNat_name"})
        df = df[df["iNat_name"].notna()]
        if "TRACK" in df.columns:
            df = df[df["TRACK"] == "Y"]
        
        for col in cols_to_keep:
            if col not in df.columns:
                df[col] = None
        
        df = df[cols_to_keep]
        overrides_df = pd.concat([overrides_df, df])
    
    print(f"Found {len(overrides_df)} records with different iNaturalist names.")

    # Write Biotics query for missing ELCODEs
    missing_elcode = len(df[df["ELCODE"].isna()])
    if args.query:
        if not missing_elcode:
            print(f"No records with missing ELCODE!")
        else:
            print(f"Found {len(df[df["ELCODE"].isna()])} entries without an ELCODE. Generating query...")
            print(biotics_query(overrides_df))
        return

    # Fill in missing ELCODEs
    if args.fill:
        elcodes_df = pd.read_csv(config["overrides"]["elcodes_csv"])
        print(f"Found {missing_elcode} entries without an ELCODE. Filling in ELCODEs from Biotics query result ({len(elcodes_df)} results).")
        overrides_df = fill_elcodes(overrides_df, elcodes_df)
    
    elcode_match_mask = ~overrides_df["ELCODE"].isna() & overrides_df["ELCODE"].isin(tracking_df["ELCODE"])
    sname_match_mask = overrides_df["SNAME"].isin(tracking_df["SNAME"])
    overrides_df = overrides_df[elcode_match_mask | sname_match_mask]
    print(f"Found {len(overrides_df)} matching records in the tracking list. Writing name overrides to file...")

    overrides_df.to_csv("taxonomy/name_maps/name_overrides.csv", index=False)

    print("Done!\n")


if __name__ == "__main__":
    main()