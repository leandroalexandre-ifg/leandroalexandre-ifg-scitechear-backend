import json

from app.api.jobs import _JOBS, _JobRecord
from app.models.result import MeetingResult


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


def test_resultado_antes_de_done_retorna_409(client):
    # Fase 1 não tem PipelineFacade: simula um job ainda em andamento inserindo
    # diretamente no store em memória (o cenário real de status != done chega
    # com os estágios de verdade na Fase 6).
    job_id = "job-em-andamento"
    _JOBS[job_id] = _JobRecord(job_id=job_id, title=None, participants=[])
    try:
        response = client.get(f"/resultado/{job_id}")
        assert response.status_code == 409
    finally:
        _JOBS.pop(job_id, None)


def test_resultado_apos_upload_valida_contra_o_schema(client, wav_bytes):
    upload_response = _upload(client, wav_bytes)
    job_id = upload_response.json()["job_id"]

    status_response = client.get(f"/status/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "done"

    result_response = client.get(f"/resultado/{job_id}")
    assert result_response.status_code == 200

    result = MeetingResult.model_validate(result_response.json())
    assert result.job_id == job_id
    assert result.metadata.stub is True
    assert len(result.segments) > 0
    assert any(q.type.value == "implicit" and q.speaker is None and q.time is None for q in result.questions)
