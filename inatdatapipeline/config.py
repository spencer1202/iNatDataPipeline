from pathlib import Path
import click
import helpers
import logging
from typing import Annotated, Optional, TypeVar
from pydantic import BeforeValidator, BaseModel, FilePath

# ---------------------------------------------------------------------------
# Pydantic stuff
# ---------------------------------------------------------------------------

def check_path(v: any, required: bool, check_exists: bool, extension: str = None) -> Optional[Path]:
    """Helper function to handle common file path checks"""
    
    # Handle missing, None, or blank strings from config file
    is_empty = v is None or (isinstance(v, str) and v.strip() == "")

    if is_empty:
        if required:
            raise ValueError("This file path is required.")
        return None
    
    path_obj = Path(v)

    # Check if the file actually exists
    if check_exists and not path_obj.exists():
        raise ValueError(f"Path does not exist: \'{v}\'")
    
    # Check for specific file extension
    if extension and path_obj.suffix.lower() != extension.lower():
        raise ValueError(f"File must use a \'{extension}\' extension.")
    
    return path_obj


OptionalExistingCSV = Annotated[Optional[Path], BeforeValidator(
    lambda v: check_path(v, required=False, check_exists=True, extension=".csv")
)]
OptionalExistingFile = Annotated[Optional[Path], BeforeValidator(
    lambda v: check_path(v, required=False, check_exists=True)
)]
RequiredExistingCSV = Annotated[Path, BeforeValidator(
    lambda v: check_path(v, required=True, check_exists=True)
)]
RequiredNewFile = Annotated[Path, BeforeValidator(
    lambda v: check_path(v, required=True, check_exists=False)
)]


# Pydantic config schemas
class ObservationsConfig(BaseModel):
    place_id            : int
    quality_grade       : str
    per_page            : int 
    batch_size          : int
    fields_json         : FilePath
    update_after_days   : int
    project_id          : int
    max_observations    : int

class CoreConfig(BaseModel):
    db_file             : RequiredNewFile
    user_agent          : str
    username            : str

class TaxaConfig(BaseModel):
    tracking_list       : RequiredExistingCSV
    name_overrides_file : RequiredExistingCSV

class ExpertsConfig(BaseModel):
    experts_file        : RequiredExistingCSV

class OverridesConfig(BaseModel):
    invertebrates_csv       : OptionalExistingCSV = None
    vertebrates_csv         : OptionalExistingCSV = None
    vascular_csv            : OptionalExistingCSV = None
    nonvascular_fungi_csv   : OptionalExistingCSV = None
    elcodes_csv             : OptionalExistingCSV = None


class Config(BaseModel):
    core            : CoreConfig
    observations    : ObservationsConfig
    taxa            : TaxaConfig
    experts         : ExpertsConfig
    overrides       : OverridesConfig



def get_validated_config(logger: logging.Logger, raw_config: dict) -> Config:
    try:
        return Config(**raw_config)
    except Exception as ex:
        logger.error(f"Invalid configuration settings:\n{ex}")
        return None