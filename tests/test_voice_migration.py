from app.repositories.voice_repository import VoiceRepository
from app.services.voice_enrollment_service import VoiceEnrollmentService
from app.services.voice_migration import migrate_legacy_voice_bank


def _criar_banco_legado(tmp_path):
    legacy_root = tmp_path / "banco_vozes"
    pasta_audios = legacy_root / "Leandro" / "audios"
    pasta_audios.mkdir(parents=True)
    (pasta_audios / "amostra1.wav").write_bytes(b"conteudo-leandro-1")
    (pasta_audios / "amostra2.wav").write_bytes(b"conteudo-leandro-2")
    return legacy_root


def test_migracao_cria_perfil_por_participant_id_sem_tocar_no_original(tmp_path):
    legacy_root = _criar_banco_legado(tmp_path)
    novo_storage = tmp_path / "storage_novo"
    service = VoiceEnrollmentService(VoiceRepository(novo_storage))

    migrados = migrate_legacy_voice_bank(
        legacy_root=legacy_root,
        name_to_participant_id={"Leandro": "p_leandro_123"},
        enrollment_service=service,
        user_id="u1",
    )

    assert len(migrados) == 1
    assert migrados[0].participant_id == "p_leandro_123"
    assert migrados[0].sample_count == 2
    assert migrados[0].display_name == "Leandro"

    # perfil migrado existe na nova estrutura, indexado por participant_id
    perfil = service.get_profile("u1", "p_leandro_123")
    assert perfil is not None
    assert perfil.sample_count == 2

    # arquivos originais do banco legado continuam intactos
    originais = sorted((legacy_root / "Leandro" / "audios").iterdir())
    assert len(originais) == 2
    assert (legacy_root / "Leandro" / "audios" / "amostra1.wav").read_bytes() == b"conteudo-leandro-1"


def test_migracao_ignora_nome_sem_mapeamento(tmp_path):
    legacy_root = _criar_banco_legado(tmp_path)
    service = VoiceEnrollmentService(VoiceRepository(tmp_path / "storage_novo"))

    migrados = migrate_legacy_voice_bank(
        legacy_root=legacy_root,
        name_to_participant_id={"OutraPessoa": "p_outro"},
        enrollment_service=service,
        user_id="u1",
    )

    assert migrados == []
    assert service.get_profile("u1", "p_outro") is None


def test_migracao_ignora_pasta_sem_audios(tmp_path):
    legacy_root = tmp_path / "banco_vozes"
    (legacy_root / "SemAudios").mkdir(parents=True)
    service = VoiceEnrollmentService(VoiceRepository(tmp_path / "storage_novo"))

    migrados = migrate_legacy_voice_bank(
        legacy_root=legacy_root,
        name_to_participant_id={"SemAudios": "p_x"},
        enrollment_service=service,
        user_id="u1",
    )

    assert migrados == []
