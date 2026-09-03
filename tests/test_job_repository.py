from datetime import datetime, timedelta, timezone

from app.models.job import JobError, JobStatusValue
from app.models.participant import Participant
from app.repositories.job_repository import (
    JobRepository,
    JobRow,
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
    assert fetched.attempts == 0


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


# ---------------------------------------------------------------------------
# next_queued / requeue_orfaos — fila real (item 2 da preparação para
# produção, ver docs/PENDENCIAS.md e docs/BACKEND_ARCHITECTURE.md)
# ---------------------------------------------------------------------------


def test_next_queued_fila_vazia_retorna_none(tmp_path):
    repo = _novo_repo(tmp_path)
    assert repo.next_queued() is None


def test_next_queued_ignora_jobs_que_ja_saíram_de_queued(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)
    repo.create(job_id="j2", title=None, participants=[], expected_speaker_count=None)
    repo.update_status("j1", JobStatusValue.DONE)

    # só j2 continua queued — j1 (embora exista) não é candidato.
    assert repo.next_queued() == "j2"


def test_next_queued_retorna_o_mais_antigo_em_queued(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)
    repo.create(job_id="j2", title=None, participants=[], expected_speaker_count=None)
    repo.create(job_id="j3", title=None, participants=[], expected_speaker_count=None)
    repo.update_status("j1", JobStatusValue.TRANSCRIBING)  # já saiu de queued

    # Congela created_at pra não depender de timing real de execução do
    # teste: entre os que continuam queued (j2, j3), j3 é o mais antigo.
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with repo._session_factory() as session:
        session.get(JobRow, "j3").created_at = t0
        session.get(JobRow, "j2").created_at = t0 + timedelta(seconds=10)
        session.commit()

    assert repo.next_queued() == "j3"


def test_requeue_orfaos_reenfileira_estagios_nao_terminais_e_ignora_o_resto(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)  # órfão
    repo.create(job_id="j2", title=None, participants=[], expected_speaker_count=None)  # terminal
    repo.create(job_id="j3", title=None, participants=[], expected_speaker_count=None)  # nunca pego

    repo.update_status("j1", JobStatusValue.DIARIZING)
    repo.update_status("j2", JobStatusValue.DONE)

    afetados = repo.requeue_orfaos(max_attempts=3)

    assert afetados == ["j1"]
    job1 = repo.get("j1")
    assert job1.status == JobStatusValue.QUEUED
    assert job1.attempts == 1
    # Intocados: j2 (terminal) e j3 (já era queued, não é órfão).
    assert repo.get("j2").status == JobStatusValue.DONE
    job3 = repo.get("j3")
    assert job3.status == JobStatusValue.QUEUED
    assert job3.attempts == 0


def test_requeue_orfaos_sem_jobs_nao_terminais_retorna_vazio(tmp_path):
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)  # queued

    assert repo.requeue_orfaos(max_attempts=3) == []


def test_requeue_orfaos_protege_contra_job_veneno_apos_exceder_max_attempts(tmp_path):
    """Job que sistematicamente derruba o worker (ex.: segfault de lib nativa
    processando um áudio específico) não pode reenfileirar para sempre."""
    repo = _novo_repo(tmp_path)
    repo.create(job_id="j1", title=None, participants=[], expected_speaker_count=None)

    # Simula 3 ciclos de crash: o worker pega o job (volta a um estágio
    # não-terminal) e "morre" antes de terminar — cada requeue_orfaos()
    # seguinte encontra o job órfão de novo.
    for tentativa_esperada in (1, 2, 3):
        repo.update_status("j1", JobStatusValue.DIARIZING)
        afetados = repo.requeue_orfaos(max_attempts=3)
        assert afetados == ["j1"]
        job = repo.get("j1")
        assert job.status == JobStatusValue.QUEUED
        assert job.attempts == tentativa_esperada

    # 4º crash: excedeu max_attempts=3 — vai para error, não reenfileira mais.
    repo.update_status("j1", JobStatusValue.DIARIZING)
    afetados = repo.requeue_orfaos(max_attempts=3)

    assert afetados == ["j1"]
    job = repo.get("j1")
    assert job.status == JobStatusValue.ERROR
    assert job.attempts == 4
    assert job.error.code == "WORKER_MAX_TENTATIVAS_EXCEDIDO"
    assert "3" in job.error.message
    assert "diarizing" in job.error.message
