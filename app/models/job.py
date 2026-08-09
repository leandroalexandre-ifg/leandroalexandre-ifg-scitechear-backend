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
