from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Participant(BaseModel):
    id: str
    name: str


class VoiceProfile(BaseModel):
    participant_id: str
    exists: bool
    sample_count: int = 0
    model_version: Optional[str] = None
    updated_at: Optional[datetime] = None


class VoiceSampleUploadResponse(BaseModel):
    participant_id: str
    sample_count: int
    model_version: Optional[str] = None
    updated_at: datetime
