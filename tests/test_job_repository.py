from datetime import datetime, timedelta, timezone

from app.models.job import JobError, JobStatusValue
from app.models.participant import Participant
from app.repositories.job_repository import (
    JobRepository,
    JobStatusEventRow,
    get_job_repository,
)


def _novo_repo(tmp_path, nome="jobs.db") -> JobRepository:
    return JobRepository(f"sqlite:///{tmp_path / nome}")


def test_create_e_get(tmp_path):
    repo = _novo_repo(tmp_path)
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
    assert fetched.job_id == record.job_id
    assert fetched.title == record.title
    assert fetched.participants == record.participants
    assert fetched.expected_speaker_count == record.expected_speaker_count
    assert fetched.status == record.status


def test_get_inexistente_retorna_none(tmp_path):
    repo = _novo_repo(tmp_path)
    assert repo.get("nao-existe") is None


def test_update_status_atualiza_status_e_updated_at(tmp_path):
    repo = _novo_repo(tmp_path)
    record = repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)
    antes = record.updated_at

    repo.update_status("j1", JobStatusValue.TRANSCRIBING)

    atualizado = repo.get("j1")
    assert atualizado.status == JobStatusValue.TRANSCRIBING
    assert atualizado.updated_at >= antes


def test_update_status_com_erro(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)

    repo.update_status("j1", JobStatusValue.ERROR, error=JobError(code="X", message="falhou"))

    job = repo.get("j1")
    assert job.status == JobStatusValue.ERROR
    assert job.error.code == "X"
    assert job.error.message == "falhou"


def test_update_status_job_inexistente_nao_quebra(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.update_status("nao-existe", JobStatusValue.DONE)  # não deve lançar


def test_get_job_repository_e_singleton():
    assert get_job_repository() is get_job_repository()


# ---------------------------------------------------------------------------
# Persistência entre "reinicializações" — item de preparação para produção
# (job_repository deixou de ser em memória; ver docs/PENDENCIAS.md)
# ---------------------------------------------------------------------------


def test_persistencia_sobrevive_a_reinicializacao_do_repositorio(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"

    repo1 = JobRepository(database_url)
    repo1.create(
        job_id="j1",
        title="Reunião",
        participants=[Participant(id="p1", name="Leandro")],
        expected_speaker_count=2,
    )
    repo1.update_status("j1", JobStatusValue.TRANSCRIBING)
    # Fecha as conexões da instância antiga — equivalente ao processo antigo
    # encerrando, antes de "religar" com uma instância nova apontando pro
    # mesmo arquivo (simula um restart do servidor).
    repo1._engine.dispose()

    repo2 = JobRepository(database_url)
    record = repo2.get("j1")

    assert record is not None
    assert record.title == "Reunião"
    assert record.participants == [Participant(id="p1", name="Leandro")]
    assert record.expected_speaker_count == 2
    # Status real, não perdido — a instância nova nunca chamou create() nem
    # update_status(), só leu o que já estava no arquivo.
    assert record.status == JobStatusValue.TRANSCRIBING
    # status_history também sobrevive (QUEUED do create + TRANSCRIBING do
    # update_status), usado por stage_durations().
    assert [status for status, _ in record.status_history] == [
        JobStatusValue.QUEUED,
        JobStatusValue.TRANSCRIBING,
    ]


def test_persistencia_preserva_erro_entre_reinicializacoes(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"

    repo1 = JobRepository(database_url)
    repo1.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)
    repo1.update_status("j1", JobStatusValue.ERROR, error=JobError(code="X", message="falhou"))
    repo1._engine.dispose()

    repo2 = JobRepository(database_url)
    record = repo2.get("j1")

    assert record.status == JobStatusValue.ERROR
    assert record.error == JobError(code="X", message="falhou")


# ---------------------------------------------------------------------------
# stage_durations — instrumentação de performance (docs/PENDENCIAS.md)
# ---------------------------------------------------------------------------


def test_stage_durations_calcula_a_partir_do_historico_de_transicoes(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)

    # Congela timestamps artificiais escrevendo direto na tabela de eventos
    # (substitui o QUEUED real criado por create(), para não depender de
    # tempo real de execução do teste).
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    eventos = [
        (JobStatusValue.QUEUED, t0),
        (JobStatusValue.TRANSCRIBING, t0 + timedelta(seconds=1)),
        (JobStatusValue.DIARIZING, t0 + timedelta(seconds=11)),  # transcribing = 10s
        (JobStatusValue.IDENTIFYING, t0 + timedelta(seconds=16)),  # diarizing = 5s
        (JobStatusValue.DONE, t0 + timedelta(seconds=16.5)),  # identifying = 0.5s
    ]
    with repo._session_factory() as session:
        session.query(JobStatusEventRow).filter_by(job_id="j1").delete()
        for status, ts in eventos:
            session.add(JobStatusEventRow(job_id="j1", status=status.value, occurred_at=ts))
        session.commit()

    duracoes = repo.stage_durations("j1")

    assert duracoes["transcribing"] == 10.0
    assert duracoes["diarizing"] == 5.0
    assert duracoes["identifying"] == 0.5
    assert "done" not in duracoes  # terminal, sem duração própria


def test_stage_durations_job_recem_criado_sem_transicoes_suficientes(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)

    assert repo.stage_durations("j1") == {}


def test_stage_durations_job_inexistente_retorna_vazio(tmp_path):
    repo = _novo_repo(tmp_path)
    assert repo.stage_durations("nao-existe") == {}
