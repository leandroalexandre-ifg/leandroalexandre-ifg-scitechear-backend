from datetime import datetime, timedelta, timezone

from app.models.job import JobError, JobStatusValue
from app.models.participant import Participant
from app.repositories.job_repository import JobRepository, get_job_repository


def test_create_e_get():
    repo = JobRepository()
    record = repo.create(
        job_id="j1",
        title="Reunião",
        participants=[Participant(id="p1", name="Leandro")],
        expected_speaker_count=2,
    )

    assert record.job_id == "j1"
    assert record.status == JobStatusValue.QUEUED
    assert record.error is None

    fetched = repo.get("j1")
    assert fetched is record


def test_get_inexistente_retorna_none():
    repo = JobRepository()
    assert repo.get("nao-existe") is None


def test_update_status_atualiza_status_e_updated_at():
    repo = JobRepository()
    record = repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)
    antes = record.updated_at

    repo.update_status("j1", JobStatusValue.TRANSCRIBING)

    atualizado = repo.get("j1")
    assert atualizado.status == JobStatusValue.TRANSCRIBING
    assert atualizado.updated_at >= antes


def test_update_status_com_erro():
    repo = JobRepository()
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)

    repo.update_status("j1", JobStatusValue.ERROR, error=JobError(code="X", message="falhou"))

    job = repo.get("j1")
    assert job.status == JobStatusValue.ERROR
    assert job.error.code == "X"
    assert job.error.message == "falhou"


def test_update_status_job_inexistente_nao_quebra():
    repo = JobRepository()
    repo.update_status("nao-existe", JobStatusValue.DONE)  # não deve lançar


def test_get_job_repository_e_singleton():
    assert get_job_repository() is get_job_repository()


# ---------------------------------------------------------------------------
# stage_durations — instrumentação de performance (Fase 1, docs/PENDENCIAS.md)
# ---------------------------------------------------------------------------


def test_stage_durations_calcula_a_partir_do_historico_de_transicoes():
    repo = JobRepository()
    record = repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)

    # Congela timestamps artificiais no próprio histórico para não depender
    # de tempo real de execução do teste.
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record.status_history = [
        (JobStatusValue.QUEUED, t0),
        (JobStatusValue.TRANSCRIBING, t0 + timedelta(seconds=1)),
        (JobStatusValue.DIARIZING, t0 + timedelta(seconds=11)),  # transcribing = 10s
        (JobStatusValue.IDENTIFYING, t0 + timedelta(seconds=16)),  # diarizing = 5s
        (JobStatusValue.DONE, t0 + timedelta(seconds=16.5)),  # identifying = 0.5s
    ]

    duracoes = repo.stage_durations("j1")

    assert duracoes["transcribing"] == 10.0
    assert duracoes["diarizing"] == 5.0
    assert duracoes["identifying"] == 0.5
    assert "done" not in duracoes  # terminal, sem duração própria


def test_stage_durations_job_recem_criado_sem_transicoes_suficientes():
    repo = JobRepository()
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)

    assert repo.stage_durations("j1") == {}


def test_stage_durations_job_inexistente_retorna_vazio():
    repo = JobRepository()
    assert repo.stage_durations("nao-existe") == {}
