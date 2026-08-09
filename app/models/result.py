from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"


class Segment(BaseModel):
    id: str
    cluster: str
    participant_id: Optional[str] = None
    speaker: Optional[str] = None
    identified: bool
    confidence: Optional[float] = None
    start: float
    end: float
    text: str


class Question(BaseModel):
    id: str
    type: QuestionType
    text: str
    participant_id: Optional[str] = None
    speaker: Optional[str] = None
    time: Optional[float] = None
    source_segment_ids: List[str] = Field(default_factory=list)


class ResultMetadata(BaseModel):
    whisperx_model: Optional[str] = None
    diarization_model: Optional[str] = None
    voice_model: Optional[str] = None
    llm_model: Optional[str] = None
    generated_at: Optional[datetime] = None
    # True enquanto o resultado vier do fixture da Fase 1 (sem PipelineFacade real).
    stub: bool = False


class MeetingResult(BaseModel):
    job_id: str
    status: Literal["done"] = "done"
    segments: List[Segment]
    questions: List[Question]
    metadata: ResultMetadata
