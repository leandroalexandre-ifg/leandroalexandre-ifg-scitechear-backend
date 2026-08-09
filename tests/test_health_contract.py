def test_health_nao_carrega_modelos(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_indica_pipeline_ainda_nao_implementado(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is False
