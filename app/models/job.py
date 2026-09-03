from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class JobStatusValue(str, Enum):
    QUEUED = "queued"
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"
    IDENTIFYING = "identifying"
    SUMMARIZING = "summarizing"
    EXTRACTING = "extracting"
    DONE = "done"
    ERROR = "error"


class JobError(BaseModel):
    code: str
    message: str


class UploadResponse(BaseModel):
    job_id: str
    status: JobStatusValue = JobStatusValue.QUEUED


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatusValue
    progress: Optional[float] = None
    error: Optional[JobError] = None
    updated_at: datetime


class MeetingSummary(BaseModel):
    """Item de GET /meetings — resumo de uma reunião do usuário autenticado,
    sem o payload completo do resultado (ver MeetingResult para isso)."""

    job_id: str
    title: Optional[str] = None
    status: JobStatusValue
    created_at: datetime
    updated_at: datetime
