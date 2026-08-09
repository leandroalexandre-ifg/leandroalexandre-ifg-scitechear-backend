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
