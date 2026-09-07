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


def _cadastrar(client, wav_bytes, participant_id, nome=None):
    files = {"file": ("amostra.wav", wav_bytes, "audio/wav")}
    data = {"name": nome} if nome else None
    response = client.post(f"/participants/{participant_id}/voice-samples", files=files, data=data)
    assert response.status_code == 200, response.text


def test_participants_lista_com_id_e_nome_para_recuperar_o_cadastro(client, wav_bytes):
    """O participant_id é gerado pelo app e vivia só no shared_preferences —
    desinstalar apagava o conjunto inteiro de ids da conta e deixava os
    perfis aqui inalcançáveis. A listagem devolve id E nome justamente para o
    app reconstruir o cadastro local em vez de recomeçar do zero."""
    _cadastrar(client, wav_bytes, "p-bruno", "Bruno Teixeira")
    _cadastrar(client, wav_bytes, "p-ana", "Ana Ribeiro")

    response = client.get("/participants")
    assert response.status_code == 200
    corpo = response.json()

    # Ordem estável por nome, para a tela não embaralhar entre duas chamadas.
    assert [p["participant_id"] for p in corpo] == ["p-ana", "p-bruno"]
    assert [p["name"] for p in corpo] == ["Ana Ribeiro", "Bruno Teixeira"]
    assert all(p["sample_count"] == 1 for p in corpo)
    assert all(p["model_version"] and p["updated_at"] for p in corpo)


def test_participants_lista_vazia_para_quem_nunca_cadastrou(client):
    assert client.get("/participants").json() == []


def test_participants_inclui_perfil_cadastrado_sem_nome(client, wav_bytes):
    """`name` é opcional no cadastro, então pode voltar nulo — o app precisa
    de um fallback, mas o id (que é o que importa recuperar) vem sempre."""
    _cadastrar(client, wav_bytes, "p-sem-nome")

    item = client.get("/participants").json()[0]
    assert item["participant_id"] == "p-sem-nome"
    assert item["name"] is None


def test_participants_nao_vaza_cadastro_de_outro_usuario(client, wav_bytes):
    from fastapi.testclient import TestClient

    from app.main import app

    _cadastrar(client, wav_bytes, "p1", "Leandro")

    outro = TestClient(app)
    outro.post("/auth/register", json={"email": "outro@exemplo.com", "password": "outra-senha-123"})
    login = outro.post("/auth/login", json={"email": "outro@exemplo.com", "password": "outra-senha-123"})
    outro.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})

    assert outro.get("/participants").json() == []
    _cadastrar(outro, wav_bytes, "p1", "Outra Pessoa")
    assert [p["name"] for p in outro.get("/participants").json()] == ["Outra Pessoa"]
    assert [p["name"] for p in client.get("/participants").json()] == ["Leandro"]


def test_participants_sem_token_retorna_401(unauthenticated_client):
    assert unauthenticated_client.get("/participants").status_code == 401


def test_participants_deixa_de_listar_o_que_foi_apagado(client, wav_bytes):
    _cadastrar(client, wav_bytes, "p1", "Leandro")
    assert client.delete("/participants/p1/voice-profile").status_code == 204
    assert client.get("/participants").json() == []
