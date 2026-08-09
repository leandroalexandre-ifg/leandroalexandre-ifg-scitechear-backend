from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi import status as http_status

from app.api.jobs import _validate_wav
from app.config import get_settings
from app.models.participant import VoiceProfile, VoiceSampleUploadResponse
from app.repositories.voice_repository import VoiceRepository
from app.services.voice_enrollment_service import VoiceEnrollmentService

router = APIRouter(tags=["participants"])


def _enrollment_service() -> VoiceEnrollmentService:
    voices_root = Path(get_settings().storage_root) / "voices"
    return VoiceEnrollmentService(VoiceRepository(voices_root))


@router.post("/participants/{participant_id}/voice-samples", response_model=VoiceSampleUploadResponse)
async def upload_voice_sample(
    participant_id: str,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
) -> VoiceSampleUploadResponse:
    _validate_wav(file)
    content = await file.read()

    service = _enrollment_service()
    try:
        profile = service.add_sample(
            participant_id=participant_id,
            content=content,
            filename_hint=file.filename or "amostra.wav",
            display_name=name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return VoiceSampleUploadResponse(
        participant_id=profile.participant_id,
        sample_count=profile.sample_count,
        model_version=profile.model_version,
        updated_at=profile.updated_at,
    )


@router.get("/participants/{participant_id}/voice-profile", response_model=VoiceProfile)
async def get_voice_profile(participant_id: str) -> VoiceProfile:
    service = _enrollment_service()
    profile = service.get_profile(participant_id)
    if profile is None:
        return VoiceProfile(participant_id=participant_id, exists=False, sample_count=0)

    return VoiceProfile(
        participant_id=participant_id,
        exists=True,
        sample_count=profile.sample_count,
        model_version=profile.model_version,
        updated_at=profile.updated_at,
    )


@router.delete("/participants/{participant_id}/voice-profile", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_voice_profile(participant_id: str) -> Response:
    service = _enrollment_service()
    service.delete_profile(participant_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
