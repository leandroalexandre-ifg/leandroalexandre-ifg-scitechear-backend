"""Artefatos de um job (áudio enviado, resultado canônico) em storage local
do runtime — nada de Google Drive ou barramento externo no caminho de
execução (regra invólavel do CLAUDE.md).

Layout:
    storage/jobs/<job_id>/
        audio.<ext>     # WAV enviado no /upload
        result.json     # resultado canônico (gerenciado por ResultRepository)
"""
from pathlib import Path
from typing import Optional


class StorageRepository:
    def __init__(self, root: Path):
        self._root = Path(root)

    def job_dir(self, job_id: str) -> Path:
        return self._root / "jobs" / job_id

    def save_audio(self, job_id: str, content: bytes, filename_hint: str) -> Path:
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename_hint).suffix or ".wav"
        path = job_dir / f"audio{suffix}"
        path.write_bytes(content)
        return path

    def audio_path(self, job_id: str) -> Optional[Path]:
        job_dir = self.job_dir(job_id)
        if not job_dir.is_dir():
            return None
        candidatos = sorted(job_dir.glob("audio.*"))
        return candidatos[0] if candidatos else None
