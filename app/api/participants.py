from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi import status as http_status

from app.api.dependencies import get_current_user_id
from app.api.jobs import _validate_wav
from app.config import get_settings
from app.models.participant import EnrolledParticipant, VoiceProfile, VoiceSampleUploadResponse
from app.repositories.voice_repository import VoiceRepository
from app.services.voice_enrollment_service import VoiceEnrollmentService

router = APIRouter(tags=["participants"])


def _enrollment_service() -> VoiceEnrollmentService:
    voices_root = Path(get_settings().storage_root) / "voices"
    return VoiceEnrollmentService(VoiceRepository(voices_root))


@router.get("/participants", response_model=List[EnrolledParticipant])
async def list_enrolled_participants(
    user_id: str = Depends(get_current_user_id),
) -> List[EnrolledParticipant]:
    """Participantes do usuário autenticado que têm perfil de voz aqui.

    Serve para o app RECUPERAR o cadastro depois de reinstalar. O
    `participant_id` é gerado pelo app e vivia só no armazenamento local
    dele, então desinstalar apagava o conjunto inteiro de ids de uma conta:
    o usuário recadastrava as mesmas pessoas, recebia ids novos, e os perfis
    antigos ficavam aqui inalcançáveis — sem rota que os listasse, ninguém
    conseguia nem contar quantos eram, quanto mais apagá-los.

    Devolve o `display_name` junto do id justamente para isto: com os dois, o
    app reconstrói a lista local em vez de recomeçar do zero.
    """
    perfis = _enrollment_service().list_profiles(user_id)
    return [
        EnrolledParticipant(
            participant_id=p.participant_id,
            name=p.display_name,
            sample_count=p.sample_count,
            model_version=p.model_version,
            updated_at=p.updated_at,
        )
        for p in perfis
    ]


@router.post("/participants/{participant_id}/voice-samples", response_model=VoiceSampleUploadResponse)
async def upload_voice_sample(
    participant_id: str,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
) -> VoiceSampleUploadResponse:
    _validate_wav(file)
    # Lê um byte a mais que o teto: se vier alguma coisa nessa posição, o
    # arquivo passou do limite — e nada além do teto chega a ficar na memória.
    limite = get_settings().max_voice_sample_bytes
    content = await file.read(limite + 1)
    if len(content) > limite:
        raise HTTPException(
            status_code=http_status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Amostra de voz excede o limite de {get_settings().max_voice_sample_mb} MB.",
        )

    service = _enrollment_service()
    try:
        profile = service.add_sample(
            user_id=user_id,
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
async def get_voice_profile(
    participant_id: str, user_id: str = Depends(get_current_user_id)
) -> VoiceProfile:
    service = _enrollment_service()
    profile = service.get_profile(user_id, participant_id)
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
async def delete_voice_profile(
    participant_id: str, user_id: str = Depends(get_current_user_id)
) -> Response:
    service = _enrollment_service()
    service.delete_profile(user_id, participant_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
