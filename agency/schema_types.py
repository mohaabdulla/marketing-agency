"""Shared strict types, independent of the record registry to avoid circular imports."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Id = Annotated[str, Field(pattern=r'^[a-f0-9]{32}$')]
Short = Annotated[str, Field(max_length=250)]
Text = Annotated[str, Field(max_length=6000)]
Tags = Annotated[list[Short], Field(max_length=50)]
Ids = Annotated[list[Id], Field(max_length=50)]
Locale = Literal['en', 'ar', 'ar-BH']
EvidenceState = Literal['verified_source', 'client_supplied', 'approved_assumption', 'unverified_hypothesis']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
