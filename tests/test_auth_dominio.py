"""Allowlist institucional de e-mail no registro.

Com a API só em loopback, registro aberto era aceitável. Alcançável pela rede
do IFG (10.4.0.0/16 é a instituição inteira), passa a significar conta para
qualquer pessoa que chegue à porta.
"""
from app.config import get_settings

DOMINIOS = "ifg.edu.br,academico.ifg.edu.br"


def _registrar(client, email: str):
    return client.post(
        "/auth/register", json={"email": email, "password": "senha-de-teste-123", "name": "Fulano"}
    )


def test_sem_allowlist_o_registro_segue_aberto(unauthenticated_client):
    """Default preserva o comportamento anterior — nada quebra para quem não
    configurar a variável."""
    assert get_settings().auth_allowed_email_domains_list == []
    assert _registrar(unauthenticated_client, "qualquer@exemplo.com").status_code == 201


def test_com_allowlist_dominio_institucional_e_aceito(unauthenticated_client, monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAINS", DOMINIOS)
    get_settings.cache_clear()

    assert _registrar(unauthenticated_client, "aluno@academico.ifg.edu.br").status_code == 201


def test_com_allowlist_dominio_de_fora_recebe_403(unauthenticated_client, monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAINS", DOMINIOS)
    get_settings.cache_clear()

    resposta = _registrar(unauthenticated_client, "estranho@gmail.com")

    assert resposta.status_code == 403
    assert "institucionais" in resposta.json()["detail"]


def test_comparacao_de_dominio_ignora_maiusculas(unauthenticated_client, monkeypatch):
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAINS", DOMINIOS)
    get_settings.cache_clear()

    assert _registrar(unauthenticated_client, "Aluno@IFG.EDU.BR").status_code == 201


def test_subdominio_parecido_nao_passa(unauthenticated_client, monkeypatch):
    """"ifg.edu.br.atacante.com" termina com o domínio permitido como texto,
    mas não é ele — a comparação é do domínio inteiro, não de sufixo."""
    monkeypatch.setenv("AUTH_ALLOWED_EMAIL_DOMAINS", DOMINIOS)
    get_settings.cache_clear()

    assert _registrar(unauthenticated_client, "x@ifg.edu.br.atacante.com").status_code == 403
