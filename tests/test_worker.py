import pytest

from app import worker
from app.config import get_settings
from app.models.job import JobStatusValue
from app.models.participant import Participant
from app.repositories.job_repository import get_job_repository


class _PararLoop(Exception):
    """Usada só para sair do `while True` de worker.main() nos testes —
    ver _fake_sleep abaixo."""


def test_worker_reenfileira_orfaos_no_boot_e_processa_a_fila(monkeypatch):
    jobs = get_job_repository()
    jobs.create(
        job_id="j1",
        title=None,
        participants=[Participant(id="p1", name="Leandro")],
        expected_speaker_count=None,
    )
    jobs.update_status("j1", JobStatusValue.DIARIZING)  # órfão de uma instância anterior

    processados = []

    def _fake_executar_job(job_id):
        # Simula o pipeline real terminando (sem rodar WhisperX/pyannote/etc.)
        # — precisa tirar o job de `queued`, senão next_queued() acharia o
        # mesmo job para sempre e o teste nunca chegaria no sleep().
        processados.append(job_id)
        jobs.update_status(job_id, JobStatusValue.DONE)

    def _fake_sleep(segundos):
        raise _PararLoop  # fila vazia = sinal de que já processamos tudo

    monkeypatch.setattr(worker, "executar_job", _fake_executar_job)
    monkeypatch.setattr(worker.time, "sleep", _fake_sleep)

    with pytest.raises(_PararLoop):
        worker.main()

    assert processados == ["j1"]
    job = jobs.get("j1")
    assert job.status == JobStatusValue.DONE
    assert job.attempts == 1  # reenfileirado uma vez antes de processar


def test_worker_ignora_jobs_ja_terminais_no_boot(monkeypatch):
    jobs = get_job_repository()
    jobs.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)
    jobs.update_status("j1", JobStatusValue.DONE)  # terminal, não é órfão

    processados = []
    monkeypatch.setattr(worker, "executar_job", lambda job_id: processados.append(job_id))
    monkeypatch.setattr(worker.time, "sleep", lambda segundos: (_ for _ in ()).throw(_PararLoop))

    with pytest.raises(_PararLoop):
        worker.main()

    assert processados == []  # nada a reenfileirar, nada a processar
    assert jobs.get("j1").status == JobStatusValue.DONE
    assert jobs.get("j1").attempts == 0


def test_worker_usa_max_attempts_configurado(monkeypatch):
    monkeypatch.setenv("WORKER_MAX_ATTEMPTS_BEFORE_ERROR", "7")
    get_settings.cache_clear()

    jobs = get_job_repository()
    chamadas_max_attempts = []
    monkeypatch.setattr(
        jobs,
        "requeue_orfaos",
        lambda max_attempts: chamadas_max_attempts.append(max_attempts) or [],
    )
    monkeypatch.setattr(worker.time, "sleep", lambda segundos: (_ for _ in ()).throw(_PararLoop))

    try:
        with pytest.raises(_PararLoop):
            worker.main()
        assert chamadas_max_attempts == [7]
    finally:
        get_settings.cache_clear()
