from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi import status as http_status

from app.api.jobs import _validate_wav
from app.config import get_settings
from app.models.participant import VoiceProfile, VoiceSampleUploadResponse

router = APIRouter(tags=["participants"])


class _VoiceProfileRecord:
    def __init__(self, participant_id: str):
        self.participant_id = participant_id
        self.sample_count = 0
        self.model_version: Optional[str] = None
        self.updated_at: Optional[datetime] = None


# Fase 1: store em memória, só para validar o contrato HTTP. Substituído por
# app/repositories/voice_repository.py (chave participant_id) na Fase 2.
_VOICE_PROFILES: Dict[str, _VoiceProfileRecord] = {}


@router.post("/participants/{participant_id}/voice-samples", response_model=VoiceSampleUploadResponse)
async def upload_voice_sample(
    participant_id: str,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
) -> VoiceSampleUploadResponse:
    _validate_wav(file)

    record = _VOICE_PROFILES.setdefault(participant_id, _VoiceProfileRecord(participant_id))
    # Fase 1: só conta a amostra recebida. O recálculo real do embedding
    # consolidado (SpeechBrain ECAPA) chega na Fase 2, via VoiceEnrollmentService.
    record.sample_count += 1
    record.model_version = get_settings().voice_model
    record.updated_at = datetime.now(timezone.utc)

    return VoiceSampleUploadResponse(
        participant_id=participant_id,
        sample_count=record.sample_count,
        model_version=record.model_version,
        updated_at=record.updated_at,
    )


@router.get("/participants/{participant_id}/voice-profile", response_model=VoiceProfile)
async def get_voice_profile(participant_id: str) -> VoiceProfile:
    record = _VOICE_PROFILES.get(participant_id)
    if record is None:
        return VoiceProfile(participant_id=participant_id, exists=False, sample_count=0)

    return VoiceProfile(
        participant_id=participant_id,
        exists=True,
        sample_count=record.sample_count,
        model_version=record.model_version,
        updated_at=record.updated_at,
    )


@router.delete("/participants/{participant_id}/voice-profile", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_voice_profile(participant_id: str) -> Response:
    _VOICE_PROFILES.pop(participant_id, None)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
