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


class EnrolledParticipant(BaseModel):
    """Item de GET /participants — um participante que TEM perfil de voz
    neste servidor.

    O backend não conhece os participantes de um usuário: eles vivem no
    cadastro local do app e chegam aqui de duas formas, ambas por reunião
    (`participants` do /upload) ou por amostra de voz. Só os que passaram
    pelo cadastro de voz deixam rastro próprio — e são exatamente os que
    importam recuperar, porque são os únicos que ocupam disco.

    `name` é o `display_name` do profile.json (o campo `name` que o app manda
    junto da amostra). Pode ser nulo em perfis cadastrados sem ele.
    """

    participant_id: str
    name: Optional[str] = None
    sample_count: int
    model_version: Optional[str] = None
    updated_at: datetime
