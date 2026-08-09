import pytest
import torch

from app.repositories.voice_repository import VoiceRepository
from app.services.voice_enrollment_service import VoiceEnrollmentService


@pytest.fixture
def service(tmp_path) -> VoiceEnrollmentService:
    return VoiceEnrollmentService(VoiceRepository(tmp_path))


def test_add_sample_cria_perfil_associado_ao_participant_id(service):
    profile = service.add_sample(
        participant_id="p1", content=b"audio-1", filename_hint="amostra1.wav", display_name="Leandro"
    )

    assert profile.participant_id == "p1"
    assert profile.sample_count == 1
    assert profile.display_name == "Leandro"
    assert profile.model_version  # veio de settings.voice_model


def test_nova_amostra_recalcula_embedding_consolidado(service):
    profile_1 = service.add_sample(participant_id="p1", content=b"audio-1", filename_hint="a1.wav")
    embedding_1 = service._repository.load_embedding("p1")

    profile_2 = service.add_sample(participant_id="p1", content=b"audio-2", filename_hint="a2.wav")
    embedding_2 = service._repository.load_embedding("p1")

    assert profile_1.sample_count == 1
    assert profile_2.sample_count == 2
    # o embedding consolidado muda porque agora é a média das DUAS amostras
    assert not torch.allclose(embedding_1, embedding_2)
    # e continua normalizado (norma L2 ~= 1)
    assert torch.isclose(embedding_2.norm(p=2), torch.tensor(1.0), atol=1e-4)


def test_display_name_e_preservado_quando_nao_informado_de_novo(service):
    service.add_sample(participant_id="p1", content=b"audio-1", filename_hint="a1.wav", display_name="Leandro")
    profile = service.add_sample(participant_id="p1", content=b"audio-2", filename_hint="a2.wav")

    assert profile.display_name == "Leandro"


def test_get_profile_inexistente_retorna_none(service):
    assert service.get_profile("ninguem") is None


def test_delete_profile_remove_perfil_e_amostras(service):
    service.add_sample(participant_id="p1", content=b"audio-1", filename_hint="a1.wav")

    assert service.delete_profile("p1") is True
    assert service.get_profile("p1") is None
    assert service._repository.list_sample_paths("p1") == []


def test_recompute_sem_amostras_leva_a_erro(service):
    with pytest.raises(ValueError):
        service._recompute_profile("ninguem")
