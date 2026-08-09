import numpy as np
import pytest
import whisperx

from app.services import transcription_service


@pytest.fixture
def stub_whisperx(monkeypatch):
    """Substitui as chamadas reais ao WhisperX por um resultado fixture —
    não precisa de GPU nem baixar modelo para validar o contrato do serviço."""

    def fake_load_audio(path):
        return np.zeros(16000, dtype="float32")  # 1s de "áudio"

    class _FakeModel:
        def transcribe(self, audio, batch_size):
            return {
                "segments": [{"start": 0.0, "end": 2.0, "text": "Bom dia a todos."}],
                "language": "pt",
            }

    def fake_load_model(model_size, device, compute_type, language):
        return _FakeModel()

    def fake_load_align_model(language_code, device):
        return object(), {}

    def fake_align(transcript, model, align_model_metadata, audio, device, return_char_alignments=False):
        return {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Bom dia a todos.",
                    "words": [
                        {"word": "Bom", "start": 0.0, "end": 0.4, "score": 0.95},
                        {"word": "dia", "start": 0.5, "end": 0.9, "score": 0.9},
                        # sem timestamp: falha pontual de alinhamento, deve ser descartada
                        {"word": "incompleta", "start": None, "end": None, "score": 0.1},
                    ],
                }
            ]
        }

    monkeypatch.setattr(whisperx, "load_audio", fake_load_audio)
    monkeypatch.setattr(whisperx, "load_model", fake_load_model)
    monkeypatch.setattr(whisperx, "load_align_model", fake_load_align_model)
    monkeypatch.setattr(whisperx, "align", fake_align)


def test_transcribe_retorna_segmentos_com_start_end_text(stub_whisperx):
    result = transcription_service.transcribe("reuniao.wav")

    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.start == 0.0
    assert segment.end == 2.0
    assert segment.text == "Bom dia a todos."


def test_transcribe_preserva_words_e_descarta_sem_timestamp(stub_whisperx):
    result = transcription_service.transcribe("reuniao.wav")

    words = result.segments[0].words
    assert len(words) == 2  # "incompleta" (sem start/end) foi descartada
    assert [w.word for w in words] == ["Bom", "dia"]


def test_transcribe_preenche_metadata(stub_whisperx):
    result = transcription_service.transcribe("reuniao.wav")

    assert result.metadata.audio_file == "reuniao.wav"
    assert result.metadata.language == "pt"
    assert result.metadata.model
    assert result.metadata.sample_rate == 16000
    assert result.metadata.pipeline_stage == "transcricao"


def test_transcribe_aceita_language_explicito(stub_whisperx):
    result = transcription_service.transcribe("reuniao.wav", language="en")
    # o idioma detectado pelo fixture ("pt") prevalece sobre o configurado,
    # igual ao notebook original (result.get("language", CONFIG["language"]))
    assert result.metadata.language == "pt"
