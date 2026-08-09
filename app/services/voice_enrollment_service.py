"""Cadastro/atualização de perfil de voz por participant_id.

Port de legacy/scripts/cadastro_vozes.py: preserva o comportamento de
consolidação (recalcula o embedding médio a partir de TODAS as amostras já
guardadas a cada cadastro/atualização — nunca incremental), só migrando a
chave de nome para participant_id. Recalcula o embedding SÓ aqui (cadastro),
nunca a cada reunião.
"""
from typing import Optional

import torch

from app.config import get_settings
from app.repositories.voice_repository import VoiceProfileRecord, VoiceRepository
from app.services import voice_service


class VoiceEnrollmentService:
    def __init__(self, repository: VoiceRepository):
        self._repository = repository

    def add_sample(
        self,
        participant_id: str,
        content: bytes,
        filename_hint: str,
        display_name: Optional[str] = None,
    ) -> VoiceProfileRecord:
        self._repository.save_sample(participant_id, filename_hint, content)
        return self._recompute_profile(participant_id, display_name=display_name)

    def _recompute_profile(
        self, participant_id: str, display_name: Optional[str] = None
    ) -> VoiceProfileRecord:
        sample_paths = self._repository.list_sample_paths(participant_id)
        if not sample_paths:
            raise ValueError(f"Nenhuma amostra de voz encontrada para {participant_id}.")

        embeddings = [voice_service.gerar_embedding(path) for path in sample_paths]
        embedding_medio = torch.stack(embeddings).mean(dim=0)
        embedding_consolidado = voice_service.normalizar_embedding(embedding_medio)

        existing = self._repository.load_profile(participant_id)
        resolved_display_name = display_name or (existing.display_name if existing else None)

        return self._repository.save_profile(
            participant_id=participant_id,
            embedding=embedding_consolidado,
            model_version=get_settings().voice_model,
            sample_count=len(sample_paths),
            display_name=resolved_display_name,
        )

    def get_profile(self, participant_id: str) -> Optional[VoiceProfileRecord]:
        return self._repository.load_profile(participant_id)

    def delete_profile(self, participant_id: str) -> bool:
        return self._repository.delete_profile(participant_id)
