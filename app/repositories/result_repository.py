"""Persistência do resultado canônico (app.models.result.MeetingResult) de
um job, como JSON em storage/jobs/<job_id>/result.json (via StorageRepository).
"""
from typing import Optional

from app.models.result import MeetingResult
from app.repositories.storage_repository import StorageRepository


class ResultRepository:
    def __init__(self, storage: StorageRepository):
        self._storage = storage

    def _result_path(self, job_id: str):
        return self._storage.job_dir(job_id) / "result.json"

    def save(self, result: MeetingResult) -> None:
        path = self._result_path(result.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    def load(self, job_id: str) -> Optional[MeetingResult]:
        path = self._result_path(job_id)
        if not path.is_file():
            return None
        return MeetingResult.model_validate_json(path.read_text(encoding="utf-8"))
