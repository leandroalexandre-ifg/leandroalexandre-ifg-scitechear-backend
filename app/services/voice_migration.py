"""Migração NÃO DESTRUTIVA do banco de vozes legado (chave = nome) para o
formato novo, indexado por participant_id.

Lê legacy/banco_vozes/<nome>/audios/*.wav e recadastra cada participante via
VoiceEnrollmentService (que copia os bytes para storage/voices/<participant_id>/
e recalcula o embedding consolidado). Os arquivos originais em legacy/ nunca
são movidos, apagados nem sobrescritos — apenas lidos.
"""
from pathlib import Path
from typing import Dict, List

from app.repositories.voice_repository import VoiceProfileRecord
from app.services.voice_enrollment_service import VoiceEnrollmentService


def migrate_legacy_voice_bank(
    legacy_root: Path,
    name_to_participant_id: Dict[str, str],
    enrollment_service: VoiceEnrollmentService,
    user_id: str,
) -> List[VoiceProfileRecord]:
    """Para cada <legacy_root>/<nome>/audios/*.wav cujo nome esteja mapeado em
    name_to_participant_id, copia as amostras para o novo participant_id e
    recalcula o perfil consolidado. Nomes sem mapeamento ou sem pasta
    audios/ são ignorados silenciosamente (mapeamento é responsabilidade de
    quem chama esta função, ex.: um script one-off).

    user_id: dono ao qual os perfis migrados são atribuídos (VoiceRepository
    é escopado por usuário desde a autenticação real, item 3 — ver
    docs/BACKEND_ARCHITECTURE.md). Esta função nunca decide sozinha qual
    conta usar; quem chama (script one-off) resolve isso primeiro.
    """
    migrated: List[VoiceProfileRecord] = []

    for nome, participant_id in name_to_participant_id.items():
        pasta_audios = legacy_root / nome / "audios"
        if not pasta_audios.is_dir():
            continue

        wavs = sorted(p for p in pasta_audios.iterdir() if p.suffix.lower() == ".wav")
        if not wavs:
            continue

        profile = None
        for wav_path in wavs:
            profile = enrollment_service.add_sample(
                user_id=user_id,
                participant_id=participant_id,
                content=wav_path.read_bytes(),
                filename_hint=wav_path.name,
                display_name=nome,
            )

        if profile is not None:
            migrated.append(profile)

    return migrated
