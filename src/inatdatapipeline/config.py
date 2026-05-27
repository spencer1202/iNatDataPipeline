"""
This module handles parsing and validating configuration settings using pydantic.
"""
from pathlib import Path
from typing import Annotated, Optional, TypeVar, Type, Tuple
import click
from pydantic import BeforeValidator, BaseModel, FilePath, StringConstraints, ValidationError

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
RequiredNewCSV = Annotated[Path, BeforeValidator(
    lambda v: check_path(v, required=True, check_exists=False, extension=".csv")
)]
NonEmptyString = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


# Pydantic config schemas
class ObservationsConfig(BaseModel):
    """Model for observations command configurations"""
    place_id            : int
    quality_grade       : NonEmptyString
    per_page            : int
    batch_size          : int
    fields_json         : FilePath
    update_after_days   : int
    project_id          : int
    max_observations    : int

class CoreConfig(BaseModel):
    """Model specifying core configuration settings"""
    db_file             : RequiredNewFile
    user_agent          : NonEmptyString
    username            : NonEmptyString

class TaxaConfig(BaseModel):
    """Model for taxon mapping command configurations"""
    tracking_list       : RequiredExistingCSV
    name_overrides_file : RequiredExistingCSV

class ReviewConfig(BaseModel):
    """Model for review command configurations"""
    experts_file        : RequiredExistingCSV
    export_csv          : RequiredNewCSV

class OverridesConfig(BaseModel):
    """Model for overrides command configurations"""
    invertebrates_csv       : OptionalExistingCSV = None
    vertebrates_csv         : OptionalExistingCSV = None
    vascular_csv            : OptionalExistingCSV = None
    nonvascular_fungi_csv   : OptionalExistingCSV = None
    elcodes_csv             : OptionalExistingCSV = None



T = TypeVar('T', bound=BaseModel)


def construct_error_message(err: ValidationError) -> list[str]:
    """
    Puts together a list of human readable error messages from a ValidationError.
    Args:
        err:
            ValidationError raised by a model constructor
        returns:
            A list of error strings
    """
    message = []
    for e in err.errors():
        field = e["loc"][0]
        code = e["type"]
        msg = e["msg"]
        message.append(f"Configuration error in field '{field}': {msg} (type={code})")
    return message


def validate_command_config(
        ctx: click.Context,
        section_name: str = None,
        model_cls: Type[T] = None
) -> Tuple[CoreConfig, Optional[T]]:
    """
    Validate the global core config section and optionally a specific subcommand.
    Arguments:
        ctx:
            Click context object loaded with configs.
        section_name:
            The name of the config section to load.
        model_cls:
            The pydantic config model to use to validate the config section.
    Returns:
        A tuple containing a validated CoreConfig model and a model of the specified type.
    """
    errors = []
    try:
        core_config = CoreConfig(**ctx.obj["core"])
    except ValidationError as err:
        errors.extend(construct_error_message(err))
        core_config = None

    try:
        if not section_name or not model_cls:
            result = (core_config, None)
        else:
            section_data = ctx.obj.get(section_name, {})
            subcommand_config = model_cls(**section_data)
            result = (core_config, subcommand_config)
    except ValidationError as err:
        errors.extend(construct_error_message(err))

    if len(errors) > 0:
        raise ValidationError("\n".join(errors))

    return result
