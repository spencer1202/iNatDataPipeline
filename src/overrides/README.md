# Name Overrides Setup
This script automates generating the name overrides CSV from the "ORBIC iNaturalist Collector Species Lists", since it takes a bit of work to get those lists in a useable form for the taxon mapping. 

If you see a file called "name_overrides.csv" in the taxonomy/name_maps directory, this has already been done for you!

Whenever a new name override needs to be added, you can either manually add it to the name_overrides.csv file, or you can download the collector species lists again and run through the steps below.

## Usage
First thing you'll need are the four "ORBIC iNaturalist Collector Species Lists" spreadsheets. Download them from Google Sheets and put them in the taxonomy/collector_lists folder. Then update invertebrates_csv, vertebrates_csv, vascular_csv, and nonvascular_fungi_csv options in the config file with the file paths for the respective spreadsheets.

```
[overrides]
invertebrates_csv = taxonomy\collector_lists\ORBIC iNaturalist Collector Species Lists - invertebrates (2025 list).csv
vertebrates_csv = taxonomy\collector_lists\ORBIC iNaturalist Collector Species Lists - vertebrates (2025 list).csv
vascular_csv = taxonomy\collector_lists\ORBIC iNaturalist Collector Species Lists - vascular plants (2024 list).csv
nonvascular_fungi_csv = taxonomy\collector_lists\ORBIC iNaturalist Collector Species Lists - nonvasc_fungi (2023 list).csv
```

Make sure the tracking_list file path in the config file is set to the full list of all tracked species, or there will be a lot of missing entries in the resulting overrides file.
```
[taxon_map]
tracking_list = taxonomy/tracking_lists/all_tracked_species.csv
```
Now run the script from the project's home directory using the -q option.
```
python name_overrides/overrides.py -q
```
This will output a Biotics query string with the names of all the species with missing ELCODEs. Paste this string into the Biotics query builder and copy the resulting CSV into the taxonomy/collector_lists directory. Then set the file path in the config file to path of the file you just moved:
```
[overrides]
...
elcodes_csv = taxonomy\collector_lists\elcodes.csv
```
Now run the script again, this time with the -f option to create the overrides file and fill in the missing ELCODEs with the ones from the Biotics output.
```
python name_overrides/overrides.py -f
```
And you're done! Now the tool can use these alternative names when creating the taxon mapping. Just be sure to update the 