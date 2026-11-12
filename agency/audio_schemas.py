"""Editable local audio operations and timed subtitle documents."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .schema_types import Strict, Id, Text, Locale


class AudioProject(Strict):
    asset_id: Id
    start_seconds: float = Field(0, ge=0, le=3600)
    end_seconds: float | None = Field(None, gt=0, le=3600)
    normalize: bool = True
    gain_db: float = Field(0, ge=-30, le=20)
    notes: Text = ''

    @model_validator(mode='after')
    def range(self):
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError('Audio end must follow start')
        return self


class Cue(Strict):
    start_seconds: float = Field(ge=0, le=86400)
    end_seconds: float = Field(gt=0, le=86400)
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def range(self):
        if round(self.end_seconds * 1000) <= round(self.start_seconds * 1000):
            raise ValueError('Each caption end must follow its start')
        if '-->' in self.text:
            raise ValueError('Caption text cannot contain a timing arrow')
        return self


class Subtitles(Strict):
    asset_id: Id | None = None
    language: Locale = 'en'
    cues: Annotated[list[Cue], Field(max_length=2000)] = []
    timing_origin: Literal['operator', 'local-asr'] = 'operator'
    reviewed: bool = False
    notes: Text = ''

    @model_validator(mode='after')
    def order(self):
        for before, after in zip(self.cues, self.cues[1:]):
            if after.start_seconds < before.end_seconds:
                raise ValueError('Captions must be ordered and must not overlap')
        return self


AUDIO_MODELS = {'audio-projects': AudioProject, 'subtitles': Subtitles}
