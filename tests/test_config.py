from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    IMPLICIT_QUESTIONS_PROMPT_VERSIONS,
    Settings,
    _PROJECT_ROOT,
    get_settings,
)


# ---------------------------------------------------------------------------
# STORAGE_ROOT — item 4 da preparação para produção: um valor relativo não
# pode depender do cwd do processo (API e worker são processos separados
# desde o item 2; se cada um iniciar de um cwd diferente, precisam mesmo
# assim concordar sobre onde o storage está fisicamente).
# ---------------------------------------------------------------------------


def test_storage_root_relativo_resolve_para_o_mesmo_absoluto_independente_do_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_ROOT", raising=False)
    get_settings.cache_clear()

    outro_dir = tmp_path / "processo-iniciado-daqui"
    outro_dir.mkdir()

    monkeypatch.chdir(outro_dir)
    resolvido_de_outro_cwd = Settings(STORAGE_ROOT="./storage").storage_root

    monkeypatch.chdir(_PROJECT_ROOT)
    resolvido_da_raiz = Settings(STORAGE_ROOT="./storage").storage_root

    assert resolvido_de_outro_cwd == resolvido_da_raiz
    assert resolvido_de_outro_cwd == str(_PROJECT_ROOT / "storage")
    get_settings.cache_clear()


def test_storage_root_relativo_e_absoluto_ancorado_em_project_root_nao_no_cwd():
    assert Settings(STORAGE_ROOT="./storage").storage_root == str(_PROJECT_ROOT / "storage")
    assert Settings(STORAGE_ROOT="storage").storage_root == str(_PROJECT_ROOT / "storage")


def test_storage_root_absoluto_passa_direto_sem_normalizar():
    """Um valor já absoluto (config explícita de produção) não é tocado —
    nem sequer normalizado (.resolve()) — para não mudar comportamento de
    quem já aponta pra um caminho absoluto de propósito (ex.: um symlink)."""
    caminho_com_redundancia = "/var/lib/scitechear/../scitechear/storage"
    assert Settings(STORAGE_ROOT=caminho_com_redundancia).storage_root == caminho_com_redundancia


def test_database_url_efetivo_deriva_de_storage_root_ja_absoluto(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings(STORAGE_ROOT="./storage", database_url=None)

    assert settings.database_url_efetivo == f"sqlite:///{_PROJECT_ROOT / 'storage' / 'jobs.db'}"
    assert Path(settings.storage_root).is_absolute()


# ---------------------------------------------------------------------------
# env_file — mesma causa raiz (achado durante a verificação manual deste
# item): carregar ".env" relativo ao cwd falha em silêncio se o processo
# iniciar de outro diretório, e TODAS as configs (não só storage_root)
# voltam ao default.
# ---------------------------------------------------------------------------


def test_env_file_e_absoluto_ancorado_em_project_root():
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).is_absolute()
    assert env_file == str(_PROJECT_ROOT / ".env")


def test_env_file_nao_muda_com_o_cwd_do_processo(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert Settings.model_config["env_file"] == str(_PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# IMPLICIT_QUESTIONS_PROMPT_VERSION — qual prompt de perguntas implícitas
# roda. Escolher o prompt errado muda o resultado da reunião inteira (o v6
# não tem validação de evidência), então um valor desconhecido tem de ser
# erro explícito na inicialização, nunca fallback silencioso.
# ---------------------------------------------------------------------------


def test_versao_do_prompt_de_implicitas_default_e_v4(monkeypatch):
    monkeypatch.delenv("IMPLICIT_QUESTIONS_PROMPT_VERSION", raising=False)
    assert Settings().implicit_questions_prompt_version == "v4"


@pytest.mark.parametrize("valor,esperado", [("v6", "v6"), ("V6", "v6"), (" v4 ", "v4")])
def test_versao_do_prompt_de_implicitas_normaliza_caixa_e_espaco(valor, esperado):
    assert Settings(IMPLICIT_QUESTIONS_PROMPT_VERSION=valor).implicit_questions_prompt_version == esperado


@pytest.mark.parametrize("valor", ["v5", "v7", "", "json", "latest"])
def test_versao_do_prompt_de_implicitas_desconhecida_falha_explicitamente(valor):
    with pytest.raises(ValidationError, match="IMPLICIT_QUESTIONS_PROMPT_VERSION"):
        Settings(IMPLICIT_QUESTIONS_PROMPT_VERSION=valor)


def test_versoes_aceitas_tem_um_arquivo_de_prompt_cada():
    """A lista em config.py e o mapa em question_service.py não podem
    divergir: uma versão aceita sem arquivo/parser correspondente falharia
    só na hora de processar uma reunião real."""
    from app.services.question_service import IMPLICIT_QUESTIONS_PROMPTS, PROMPTS_DIR

    assert set(IMPLICIT_QUESTIONS_PROMPTS) == set(IMPLICIT_QUESTIONS_PROMPT_VERSIONS)
    for arquivo in IMPLICIT_QUESTIONS_PROMPTS.values():
        assert (PROMPTS_DIR / arquivo).is_file()
