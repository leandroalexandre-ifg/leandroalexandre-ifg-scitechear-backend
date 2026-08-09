import pytest

from app.config import get_settings
from app.services import diarization_service
from app.services.diarization_service import _atribuir_clusters
from app.services.transcription_service import TranscribedSegment, TranscriptionMetadata, TranscriptionResult


@pytest.fixture(autouse=True)
def reset_pipeline_cache():
    diarization_service._pipeline = None
    yield
    diarization_service._pipeline = None


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

    def __call__(self, audio_path, **kwargs):
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
