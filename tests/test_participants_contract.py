def test_voice_profile_inexistente_retorna_exists_false(client):
    response = client.get("/participants/p-999/voice-profile")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["sample_count"] == 0


def test_upload_voice_sample_atualiza_perfil_e_delete_remove(client, wav_bytes):
    files = {"file": ("amostra.wav", wav_bytes, "audio/wav")}
    upload = client.post("/participants/p1/voice-samples", files=files)
    assert upload.status_code == 200
    assert upload.json()["sample_count"] == 1

    profile = client.get("/participants/p1/voice-profile")
    assert profile.status_code == 200
    body = profile.json()
    assert body["exists"] is True
    assert body["sample_count"] == 1

    delete = client.delete("/participants/p1/voice-profile")
    assert delete.status_code == 204

    profile_after_delete = client.get("/participants/p1/voice-profile")
    assert profile_after_delete.json()["exists"] is False


def test_upload_voice_sample_extensao_invalida_e_rejeitada(client, wav_bytes):
    files = {"file": ("amostra.mp3", wav_bytes, "audio/mpeg")}
    response = client.post("/participants/p2/voice-samples", files=files)
    assert response.status_code == 422


def test_voice_samples_sem_token_retorna_401(unauthenticated_client, wav_bytes):
    files = {"file": ("amostra.wav", wav_bytes, "audio/wav")}
    response = unauthenticated_client.post("/participants/p1/voice-samples", files=files)
    assert response.status_code == 401


def test_perfil_de_voz_e_isolado_por_usuario(client, wav_bytes):
    """Item 3 (Opção A, isolamento por usuário): mesmo participant_id usado
    por duas contas diferentes não compartilha perfil — cada conta só vê o
    que ela mesma cadastrou."""
    from fastapi.testclient import TestClient

    from app.main import app

    files = {"file": ("amostra.wav", wav_bytes, "audio/wav")}
    upload = client.post("/participants/p1/voice-samples", files=files)
    assert upload.status_code == 200

    outro = TestClient(app)
    outro.post("/auth/register", json={"email": "conta-b@scitechear.example.com", "password": "senha-conta-b-123"})
    login = outro.post("/auth/login", json={"email": "conta-b@scitechear.example.com", "password": "senha-conta-b-123"})
    outro.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

    profile_outro = outro.get("/participants/p1/voice-profile")
    assert profile_outro.status_code == 200
    assert profile_outro.json()["exists"] is False
