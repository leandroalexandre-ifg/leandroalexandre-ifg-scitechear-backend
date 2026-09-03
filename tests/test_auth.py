from app.config import get_settings

EMAIL = "usuario@scitechear.example.com"
PASSWORD = "senha-forte-123"


def _registrar(client, email=EMAIL, password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password, "name": "Usuário"})


def _logar(client, email=EMAIL, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


def test_register_cria_conta(unauthenticated_client):
    response = _registrar(unauthenticated_client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert body["name"] == "Usuário"
    assert "user_id" in body
    assert "password" not in body and "password_hash" not in body


def test_register_email_duplicado_retorna_409(unauthenticated_client):
    _registrar(unauthenticated_client)
    response = _registrar(unauthenticated_client)
    assert response.status_code == 409


def test_register_senha_curta_retorna_422(unauthenticated_client):
    response = unauthenticated_client.post(
        "/auth/register", json={"email": EMAIL, "password": "curta"}
    )
    assert response.status_code == 422


def test_register_email_invalido_retorna_422(unauthenticated_client):
    response = unauthenticated_client.post(
        "/auth/register", json={"email": "nao-e-email", "password": PASSWORD}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_credenciais_validas_retorna_par_de_tokens(unauthenticated_client):
    _registrar(unauthenticated_client)
    response = _logar(unauthenticated_client)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == get_settings().jwt_access_token_expire_minutes * 60


def test_login_senha_errada_retorna_401(unauthenticated_client):
    _registrar(unauthenticated_client)
    response = _logar(unauthenticated_client, password="senha-errada")
    assert response.status_code == 401


def test_login_email_inexistente_retorna_401(unauthenticated_client):
    response = _logar(unauthenticated_client, email="ninguem@scitechear.example.com")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


def test_me_com_token_valido(unauthenticated_client):
    _registrar(unauthenticated_client)
    token = _logar(unauthenticated_client).json()["access_token"]

    response = unauthenticated_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_me_sem_token_retorna_401(unauthenticated_client):
    assert unauthenticated_client.get("/auth/me").status_code == 401


def test_me_com_token_invalido_retorna_401(unauthenticated_client):
    response = unauthenticated_client.get("/auth/me", headers={"Authorization": "Bearer token-invalido"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Refresh — rotação e revogação
# ---------------------------------------------------------------------------


def test_refresh_emite_novo_par_e_revoga_o_antigo(unauthenticated_client):
    _registrar(unauthenticated_client)
    par_original = _logar(unauthenticated_client).json()

    response = unauthenticated_client.post(
        "/auth/refresh", json={"refresh_token": par_original["refresh_token"]}
    )
    assert response.status_code == 200
    novo_par = response.json()
    assert novo_par["access_token"] != par_original["access_token"]
    assert novo_par["refresh_token"] != par_original["refresh_token"]

    # o refresh token antigo já foi revogado pela rotação — reuso falha
    reuso = unauthenticated_client.post(
        "/auth/refresh", json={"refresh_token": par_original["refresh_token"]}
    )
    assert reuso.status_code == 401


def test_refresh_com_token_invalido_retorna_401(unauthenticated_client):
    response = unauthenticated_client.post("/auth/refresh", json={"refresh_token": "lixo"})
    assert response.status_code == 401


def test_refresh_com_access_token_no_lugar_de_refresh_retorna_401(unauthenticated_client):
    """access_token e refresh_token têm claim 'type' diferente — um não
    serve no lugar do outro, mesmo assinados com o mesmo segredo."""
    _registrar(unauthenticated_client)
    access_token = _logar(unauthenticated_client).json()["access_token"]

    response = unauthenticated_client.post("/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Logout — idempotente, revoga de verdade
# ---------------------------------------------------------------------------


def test_logout_revoga_refresh_token(unauthenticated_client):
    _registrar(unauthenticated_client)
    par = _logar(unauthenticated_client).json()

    logout = unauthenticated_client.post("/auth/logout", json={"refresh_token": par["refresh_token"]})
    assert logout.status_code == 204

    refresh_apos_logout = unauthenticated_client.post(
        "/auth/refresh", json={"refresh_token": par["refresh_token"]}
    )
    assert refresh_apos_logout.status_code == 401


def test_logout_com_token_invalido_e_idempotente_nao_vaza_erro(unauthenticated_client):
    response = unauthenticated_client.post("/auth/logout", json={"refresh_token": "nunca-existiu"})
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Rotas existentes exigem token
# ---------------------------------------------------------------------------


def test_rota_protegida_sem_token_retorna_401(unauthenticated_client):
    assert unauthenticated_client.get("/meetings").status_code == 401


def test_health_continua_publico(unauthenticated_client):
    assert unauthenticated_client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting — ajuste 1 aprovado antes da implementação
# ---------------------------------------------------------------------------


def test_login_bloqueia_apos_exceder_max_tentativas(unauthenticated_client, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_ATTEMPTS", "3")
    get_settings.cache_clear()
    try:
        _registrar(unauthenticated_client)

        for _ in range(3):
            resposta = _logar(unauthenticated_client, password="senha-errada")
            assert resposta.status_code == 401

        bloqueado = _logar(unauthenticated_client, password="senha-errada")
        assert bloqueado.status_code == 429
        assert "Retry-After" in bloqueado.headers

        # mesmo a senha CORRETA é recusada enquanto bloqueado — rate limit
        # age antes de checar a senha.
        ainda_bloqueado = _logar(unauthenticated_client)
        assert ainda_bloqueado.status_code == 429
    finally:
        get_settings.cache_clear()


def test_login_bem_sucedido_limpa_contador_de_falhas(unauthenticated_client, monkeypatch):
    monkeypatch.setenv("AUTH_LOGIN_MAX_ATTEMPTS", "3")
    get_settings.cache_clear()
    try:
        _registrar(unauthenticated_client)

        for _ in range(2):
            _logar(unauthenticated_client, password="senha-errada")

        assert _logar(unauthenticated_client).status_code == 200

        # contador voltou a zero — duas falhas de novo não bloqueiam ainda
        for _ in range(2):
            resposta = _logar(unauthenticated_client, password="senha-errada")
            assert resposta.status_code == 401
    finally:
        get_settings.cache_clear()


def test_register_bloqueia_apos_exceder_max_tentativas_do_mesmo_ip(unauthenticated_client, monkeypatch):
    monkeypatch.setenv("AUTH_REGISTER_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    try:
        _registrar(unauthenticated_client, email="a@scitechear.example.com")
        # 2 falhas (e-mail já cadastrado) do mesmo IP — cada uma conta como
        # tentativa para o rate limit de /auth/register.
        _registrar(unauthenticated_client, email="a@scitechear.example.com")
        _registrar(unauthenticated_client, email="a@scitechear.example.com")

        bloqueado = _registrar(unauthenticated_client, email="b@scitechear.example.com")
        assert bloqueado.status_code == 429
    finally:
        get_settings.cache_clear()
