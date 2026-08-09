"""Persistência do perfil biométrico de voz, indexada por participant_id
(nunca por nome — regra invólavel do CLAUDE.md).

Layout em disco (spec seção 7.4):

    storage/voices/<participant_id>/
        profile.json   # participant_id, display_name, model_version, sample_count, updated_at
        embedding.pt   # embedding normalizado consolidado
        samples/
            <uuid>.wav
"""
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import torch


@dataclass
class VoiceProfileRecord:
    participant_id: str
    display_name: Optional[str]
    model_version: Optional[str]
    sample_count: int
    updated_at: datetime


class VoiceRepository:
    def __init__(self, root: Path):
        self._root = Path(root)

    def _participant_dir(self, participant_id: str) -> Path:
        return self._root / participant_id

    def _samples_dir(self, participant_id: str) -> Path:
        return self._participant_dir(participant_id) / "samples"

    def _profile_path(self, participant_id: str) -> Path:
        return self._participant_dir(participant_id) / "profile.json"

    def _embedding_path(self, participant_id: str) -> Path:
        return self._participant_dir(participant_id) / "embedding.pt"

    def save_sample(self, participant_id: str, filename_hint: str, content: bytes) -> Path:
        samples_dir = self._samples_dir(participant_id)
        samples_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename_hint).suffix or ".wav"
        sample_path = samples_dir / f"{uuid.uuid4()}{suffix}"
        sample_path.write_bytes(content)
        return sample_path

    def list_sample_paths(self, participant_id: str) -> List[Path]:
        samples_dir = self._samples_dir(participant_id)
        if not samples_dir.is_dir():
            return []
        return sorted(p for p in samples_dir.iterdir() if p.suffix.lower() == ".wav")

    def save_profile(
        self,
        participant_id: str,
        embedding: torch.Tensor,
        model_version: str,
        sample_count: int,
        display_name: Optional[str] = None,
    ) -> VoiceProfileRecord:
        participant_dir = self._participant_dir(participant_id)
        participant_dir.mkdir(parents=True, exist_ok=True)

        torch.save(embedding, self._embedding_path(participant_id))

        record = VoiceProfileRecord(
            participant_id=participant_id,
            display_name=display_name,
            model_version=model_version,
            sample_count=sample_count,
            updated_at=datetime.now(timezone.utc),
        )
        payload = asdict(record)
        payload["updated_at"] = record.updated_at.isoformat()
        self._profile_path(participant_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return record

    def load_profile(self, participant_id: str) -> Optional[VoiceProfileRecord]:
        profile_path = self._profile_path(participant_id)
        if not profile_path.is_file():
            return None

        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return VoiceProfileRecord(
            participant_id=data["participant_id"],
            display_name=data.get("display_name"),
            model_version=data.get("model_version"),
            sample_count=data.get("sample_count", 0),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def load_embedding(self, participant_id: str) -> Optional[torch.Tensor]:
        embedding_path = self._embedding_path(participant_id)
        if not embedding_path.is_file():
            return None
        return torch.load(embedding_path)

    def delete_profile(self, participant_id: str) -> bool:
        participant_dir = self._participant_dir(participant_id)
        if not participant_dir.is_dir():
            return False
        shutil.rmtree(participant_dir)
        return True
