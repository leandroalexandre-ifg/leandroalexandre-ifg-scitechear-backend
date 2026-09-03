import json
from pathlib import Path

from app.config import get_settings
from app.models.job import JobError, JobStatusValue
from app.models.participant import Participant
from app.models.result import MeetingResult, Question, QuestionType, ResultMetadata, Segment
from app.repositories.job_repository import get_job_repository
from app.repositories.result_repository import ResultRepository
from app.repositories.storage_repository import StorageRepository


# Os testes de contrato validam o wiring HTTP, não o pipeline pesado (isso já
# é coberto por tests/test_pipeline_facade.py, com mocks das etapas). Não
# precisam mais mockar nenhum executor: /upload só grava o job no banco —
# quem processaria de verdade é o worker dedicado (app/worker.py), um
# processo separado que os testes de API nunca sobem.


def _upload(client, wav_bytes, participants=None, title="Reunião de teste", expected_speaker_count=None):
    participants = participants if participants is not None else [{"id": "p1", "name": "Leandro"}]
    data = {"title": title, "participants": json.dumps(participants)}
    if expected_speaker_count is not None:
        data["expected_speaker_count"] = str(expected_speaker_count)
    files = {"file": ("reuniao.wav", wav_bytes, "audio/wav")}
    return client.post("/upload", data=data, files=files)


def test_upload_valido_responde_202_com_job_id(client, wav_bytes):
    response = _upload(client, wav_bytes)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"]


def test_upload_extensao_invalida_e_rejeitado(client, wav_bytes):
    data = {"title": "x", "participants": json.dumps([{"id": "p1", "name": "Leandro"}])}
    files = {"file": ("reuniao.mp3", wav_bytes, "audio/mpeg")}
    response = client.post("/upload", data=data, files=files)
    assert response.status_code == 422


def test_upload_participants_malformado_e_rejeitado(client, wav_bytes):
    data = {"title": "x", "participants": "not-json"}
    files = {"file": ("reuniao.wav", wav_bytes, "audio/wav")}
    response = client.post("/upload", data=data, files=files)
    assert response.status_code == 422


def test_status_job_inexistente_retorna_404(client):
    response = client.get("/status/job-que-nao-existe")
    assert response.status_code == 404


def test_resultado_job_inexistente_retorna_404(client):
    response = client.get("/resultado/job-que-nao-existe")
    assert response.status_code == 404


def test_status_apos_upload_fica_queued_sem_pipeline_disparado(client, wav_bytes):
    # /upload não dispara processamento nenhum (isso é papel do worker
    # dedicado, um processo separado que este teste nunca sobe) — o status
    # real só avança quando o PipelineFacade roda de verdade (fora deste teste).
    job_id = _upload(client, wav_bytes).json()["job_id"]

    response = client.get(f"/status/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_resultado_antes_de_done_retorna_409(client, wav_bytes):
    job_id = _upload(client, wav_bytes).json()["job_id"]

    response = client.get(f"/resultado/{job_id}")
    assert response.status_code == 409


def test_resultado_apos_pipeline_concluido_valida_contra_schema(client):
    # Simula o PipelineFacade já tendo concluído: job DONE + resultado
    # persistido via os repositories reais (sem rodar WhisperX/pyannote/etc.).
    job_repo = get_job_repository()
    job_repo.create(
        job_id="job-done-1",
        title="Reunião concluída",
        participants=[Participant(id="p1", name="Leandro")],
        expected_speaker_count=None,
    )
    job_repo.update_status("job-done-1", JobStatusValue.DONE)

    storage = StorageRepository(Path(get_settings().storage_root))
    resultado = MeetingResult(
        job_id="job-done-1",
        segments=[
            Segment(
                id="seg_0001",
                cluster="SPEAKER_00",
                participant_id="p1",
                speaker="Leandro",
                identified=True,
                confidence=0.9,
                start=0.0,
                end=2.0,
                text="Bom dia.",
            )
        ],
        questions=[
            Question(
                id="P1",
                type=QuestionType.EXPLICIT,
                text="Qual é o prazo?",
                participant_id="p1",
                speaker="Leandro",
                time=1.0,
                source_segment_ids=["seg_0001"],
            )
        ],
        metadata=ResultMetadata(stub=False),
    )
    ResultRepository(storage).save(resultado)

    response = client.get("/resultado/job-done-1")
    assert response.status_code == 200

    body = MeetingResult.model_validate(response.json())
    assert body.job_id == "job-done-1"
    assert body.metadata.stub is False
    assert body.segments[0].participant_id == "p1"


def test_resultado_apos_erro_continua_409_com_status_error(client):
    job_repo = get_job_repository()
    job_repo.create(job_id="job-com-erro", title=None, participants=[], expected_speaker_count=None)
    job_repo.update_status(
        "job-com-erro",
        JobStatusValue.ERROR,
        error=JobError(code="TRANSCRIPTION_ERROR", message="modelo indisponível"),
    )

    status_response = client.get("/status/job-com-erro")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "TRANSCRIPTION_ERROR"

    result_response = client.get("/resultado/job-com-erro")
    assert result_response.status_code == 409
