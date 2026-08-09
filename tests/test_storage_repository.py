from app.repositories.storage_repository import StorageRepository


def test_save_audio_e_audio_path(tmp_path):
    repo = StorageRepository(tmp_path)

    path = repo.save_audio("job-1", b"conteudo-wav", "reuniao.wav")

    assert path.exists()
    assert path.read_bytes() == b"conteudo-wav"
    assert repo.audio_path("job-1") == path


def test_audio_path_sem_upload_retorna_none(tmp_path):
    repo = StorageRepository(tmp_path)
    assert repo.audio_path("nao-existe") is None


def test_save_audio_preserva_extensao_do_arquivo_original(tmp_path):
    repo = StorageRepository(tmp_path)
    path = repo.save_audio("job-1", b"x", "gravacao_reuniao.WAV")
    assert path.suffix == ".WAV"
