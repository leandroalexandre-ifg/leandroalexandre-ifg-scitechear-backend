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
