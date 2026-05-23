"""
Utility script to split up the taxon tracking list into separate files by the first 
letter of their elcode.
"""

import pandas as pd

df = pd.read_csv("taxonomy/all_tracked.csv", encoding="latin-1")

letter_groups = {letter: df[df["ELCODE_BCD"].str.startswith(letter)] for letter in df["ELCODE_BCD"].str[0].unique()}

for letter, group in letter_groups.items():
    filename = f"taxonomy/elcode_tracking_{letter.lower()}.csv"
    group.to_csv(filename, index=False)