import io
import wave

import pytest
import torch

from app.config import get_settings
from app.services import diarization_service
from app.services.diarization_service import _atribuir_clusters
from app.services.diarization_service import _carregar_waveform as _carregar_waveform_real
from app.services.transcription_service import TranscribedSegment, TranscriptionMetadata, TranscriptionResult


@pytest.fixture(autouse=True)
def reset_pipeline_cache():
    diarization_service._pipeline = None
    yield
    diarization_service._pipeline = None


@pytest.fixture(autouse=True)
def stub_carregar_waveform(monkeypatch):
    """`diarizar()` agora lê o áudio (soundfile) antes de chamar o pipeline —
    os testes de orquestração usam um caminho fake ("reuniao.wav"), então
    isolamos a leitura real de arquivo aqui. O carregamento em si tem teste
    dedicado com um WAV de verdade (test_carregar_waveform_*)."""
    monkeypatch.setattr(
        diarization_service,
        "_carregar_waveform",
        lambda caminho_audio: {"waveform": torch.zeros(1, 16000), "sample_rate": 16000},
    )


class _FakeSegment:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _FakeAnnotation:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=False):
        for start, end, label in self._tracks:
            yield _FakeSegment(start, end), None, label


class _FakeDiarizeOutput:
    def __init__(self, tracks):
        self.speaker_diarization = _FakeAnnotation(tracks)


class _FakePipeline:
    def __init__(self, tracks):
        self._tracks = tracks
        self.last_call_kwargs = None
        self.last_audio_input = None

    def __call__(self, audio_input, **kwargs):
        self.last_audio_input = audio_input
        self.last_call_kwargs = kwargs
        return _FakeDiarizeOutput(self._tracks)


def _transcricao_com_dois_segmentos() -> TranscriptionResult:
    return TranscriptionResult(
        metadata=TranscriptionMetadata(
            audio_file="reuniao.wav",
            generated_at="2026-01-01T00:00:00Z",
            model="turbo",
            language="pt",
            duration_seconds=10.0,
            sample_rate=16000,
        ),
        segments=[
            TranscribedSegment(id=0, start=0.0, end=2.0, text="Bom dia a todos."),
            TranscribedSegment(id=1, start=5.0, end=7.0, text="Qual é o prazo?"),
        ],
    )


def test_atribuir_clusters_escolhe_maior_sobreposicao_temporal():
    transcricao = [{"start": 0.0, "end": 2.0}, {"start": 5.0, "end": 7.0}]
    diarizados = [
        {"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
        {"start": 1.5, "end": 3.0, "speaker": "SPEAKER_01"},
        {"start": 4.9, "end": 7.1, "speaker": "SPEAKER_00"},
    ]

    clusters = _atribuir_clusters(transcricao, diarizados)

    # segmento 0 (0-2s) tem mais overlap com SPEAKER_00 (0-1.5s = 1.5s) do que
    # com SPEAKER_01 (1.5-2s = 0.5s)
    assert clusters[0] == "SPEAKER_00"
    # segmento 1 (5-7s) sobrepõe quase inteiramente com o segundo trecho de SPEAKER_00
    assert clusters[1] == "SPEAKER_00"


def test_atribuir_clusters_sem_sobreposicao_fica_desconhecido():
    transcricao = [{"start": 100.0, "end": 102.0}]
    diarizados = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]

    clusters = _atribuir_clusters(transcricao, diarizados)

    assert clusters == ["Desconhecido"]


def test_diarizar_atribui_cluster_a_cada_segmento(monkeypatch):
    fake_pipeline = _FakePipeline(
        tracks=[
            (0.0, 2.5, "SPEAKER_00"),
            (4.5, 7.5, "SPEAKER_01"),
        ]
    )
    monkeypatch.setattr(diarization_service, "carregar_pipeline", lambda: fake_pipeline)

    resultado = diarization_service.diarizar("reuniao.wav", _transcricao_com_dois_segmentos())

    assert [s.cluster for s in resultado.segments] == ["SPEAKER_00", "SPEAKER_01"]
    assert resultado.segments[0].text == "Bom dia a todos."


def test_diarizar_usa_limites_configuraveis_por_padrao(monkeypatch):
    monkeypatch.setenv("DIARIZATION_MIN_SPEAKERS", "2")
    monkeypatch.setenv("DIARIZATION_MAX_SPEAKERS", "6")
    get_settings.cache_clear()

    fake_pipeline = _FakePipeline(tracks=[(0.0, 2.5, "SPEAKER_00"), (4.5, 7.5, "SPEAKER_00")])
    monkeypatch.setattr(diarization_service, "carregar_pipeline", lambda: fake_pipeline)

    diarization_service.diarizar("reuniao.wav", _transcricao_com_dois_segmentos())

    # nada de 4/7 fixos: usa exatamente os valores configurados via env
    assert fake_pipeline.last_call_kwargs == {"min_speakers": 2, "max_speakers": 6}
    get_settings.cache_clear()


def test_diarizar_usa_expected_speaker_count_como_max_speakers_pista(monkeypatch):
    fake_pipeline = _FakePipeline(tracks=[(0.0, 2.5, "SPEAKER_00"), (4.5, 7.5, "SPEAKER_00")])
    monkeypatch.setattr(diarization_service, "carregar_pipeline", lambda: fake_pipeline)

    diarization_service.diarizar(
        "reuniao.wav", _transcricao_com_dois_segmentos(), expected_speaker_count=3
    )

    assert fake_pipeline.last_call_kwargs["max_speakers"] == 3
    assert "num_speakers" not in fake_pipeline.last_call_kwargs


def test_diarizar_usa_num_speakers_exato_so_quando_solicitado(monkeypatch):
    fake_pipeline = _FakePipeline(tracks=[(0.0, 2.5, "SPEAKER_00"), (4.5, 7.5, "SPEAKER_00")])
    monkeypatch.setattr(diarization_service, "carregar_pipeline", lambda: fake_pipeline)

    diarization_service.diarizar(
        "reuniao.wav",
        _transcricao_com_dois_segmentos(),
        expected_speaker_count=3,
        exact_speaker_count=True,
    )

    assert fake_pipeline.last_call_kwargs == {"num_speakers": 3}


def test_carregar_pipeline_sem_hf_token_levanta_erro(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError):
        diarization_service.carregar_pipeline()

    get_settings.cache_clear()


def test_import_do_modulo_nao_exige_hf_token():
    # já foi importado no topo do arquivo sem HF_TOKEN necessariamente
    # configurado — se o import tivesse carregado o pipeline, este teste
    # nem chegaria a rodar.
    assert diarization_service._pipeline is None


def test_diarizar_passa_dict_waveform_para_o_pipeline_nao_caminho_de_arquivo(monkeypatch):
    # Regressão: pipeline(str(caminho)) faz o pyannote tentar ler o arquivo
    # via torchcodec (exige FFmpeg 4-7 linkado) e falha em qualquer ambiente
    # sem essa lib. pipeline({"waveform":...,"sample_rate":...}) evita isso.
    fake_pipeline = _FakePipeline(tracks=[(0.0, 2.5, "SPEAKER_00"), (4.5, 7.5, "SPEAKER_00")])
    monkeypatch.setattr(diarization_service, "carregar_pipeline", lambda: fake_pipeline)

    diarization_service.diarizar("reuniao.wav", _transcricao_com_dois_segmentos())

    assert isinstance(fake_pipeline.last_audio_input, dict)
    assert set(fake_pipeline.last_audio_input.keys()) == {"waveform", "sample_rate"}
    assert not isinstance(fake_pipeline.last_audio_input, (str,))


def _wav_bytes_mono_16k(duracao_s: float = 0.5) -> bytes:
    buffer = io.BytesIO()
    n_amostras = int(16000 * duracao_s)
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * n_amostras)
    return buffer.getvalue()


def test_carregar_waveform_le_wav_real_sem_torchcodec(tmp_path):
    # _carregar_waveform usa soundfile (não torchaudio.load/torchcodec) —
    # este teste roda com um WAV de verdade em disco, sem mockar a leitura.
    # Usa a referência capturada ANTES do monkeypatch autouse (que substitui
    # o atributo no módulo, não o objeto função original importado aqui).
    caminho = tmp_path / "amostra.wav"
    caminho.write_bytes(_wav_bytes_mono_16k(duracao_s=0.5))

    waveform_dict = _carregar_waveform_real(caminho)

    assert set(waveform_dict.keys()) == {"waveform", "sample_rate"}
    assert waveform_dict["sample_rate"] == 16000
    assert isinstance(waveform_dict["waveform"], torch.Tensor)
    assert waveform_dict["waveform"].shape[0] == 1  # (canal, tempo), mono
    assert waveform_dict["waveform"].shape[1] == 8000  # 0.5s * 16000
