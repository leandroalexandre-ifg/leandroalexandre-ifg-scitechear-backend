import torch

from app.repositories.voice_repository import VoiceRepository


def test_save_and_load_profile_roundtrip(tmp_path):
    repo = VoiceRepository(tmp_path)
    embedding = torch.rand(192)

    saved = repo.save_profile(
        user_id="u1",
        participant_id="p1",
        embedding=embedding,
        model_version="speechbrain/spkrec-ecapa-voxceleb",
        sample_count=2,
        display_name="Leandro",
    )
    assert saved.participant_id == "p1"

    loaded = repo.load_profile("u1", "p1")
    assert loaded is not None
    assert loaded.participant_id == "p1"
    assert loaded.display_name == "Leandro"
    assert loaded.sample_count == 2
    assert loaded.model_version == "speechbrain/spkrec-ecapa-voxceleb"

    loaded_embedding = repo.load_embedding("u1", "p1")
    assert torch.allclose(loaded_embedding, embedding)


def test_load_profile_inexistente_retorna_none(tmp_path):
    repo = VoiceRepository(tmp_path)
    assert repo.load_profile("u1", "nao-existe") is None
    assert repo.load_embedding("u1", "nao-existe") is None


def test_save_sample_e_list_sample_paths(tmp_path):
    repo = VoiceRepository(tmp_path)
    repo.save_sample("u1", "p1", "amostra1.wav", b"conteudo-1")
    repo.save_sample("u1", "p1", "amostra2.wav", b"conteudo-2")

    paths = repo.list_sample_paths("u1", "p1")
    assert len(paths) == 2
    assert all(p.suffix == ".wav" for p in paths)


def test_list_sample_paths_sem_amostras_retorna_vazio(tmp_path):
    repo = VoiceRepository(tmp_path)
    assert repo.list_sample_paths("u1", "ninguem") == []


def test_delete_profile_remove_tudo(tmp_path):
    repo = VoiceRepository(tmp_path)
    repo.save_sample("u1", "p1", "amostra.wav", b"conteudo")
    repo.save_profile(
        user_id="u1", participant_id="p1", embedding=torch.rand(192), model_version="v1", sample_count=1
    )

    assert repo.delete_profile("u1", "p1") is True
    assert repo.load_profile("u1", "p1") is None
    assert repo.list_sample_paths("u1", "p1") == []


def test_delete_profile_inexistente_retorna_false(tmp_path):
    repo = VoiceRepository(tmp_path)
    assert repo.delete_profile("u1", "nao-existe") is False


def test_mesmo_participant_id_isolado_entre_usuarios(tmp_path):
    """Item 3 (Opção A): participant_id não é mais globalmente único — só
    dentro do namespace de cada usuário."""
    repo = VoiceRepository(tmp_path)
    repo.save_profile(
        user_id="u1", participant_id="p1", embedding=torch.rand(192), model_version="v1", sample_count=1
    )

    assert repo.load_profile("u1", "p1") is not None
    assert repo.load_profile("u2", "p1") is None
