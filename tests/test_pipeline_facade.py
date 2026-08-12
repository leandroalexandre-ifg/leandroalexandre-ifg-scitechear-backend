import torch

from app.models.job import JobStatusValue
from app.models.participant import Participant
from app.models.result import Question, QuestionType, Segment
from app.repositories.job_repository import JobRepository
from app.repositories.result_repository import ResultRepository
from app.repositories.storage_repository import StorageRepository
from app.repositories.voice_repository import VoiceRepository
from app.services import diarization_service, question_service, transcription_service, voice_service
from app.services.diarization_service import DiarizationResult, DiarizedSegment
from app.services.pipeline_facade import MeetingPipelineFacade
from app.services.transcription_service import TranscriptionMetadata, TranscriptionResult


def _nova_facade(tmp_path):
    storage = StorageRepository(tmp_path)
    facade = MeetingPipelineFacade(
        job_repository=JobRepository(),
        result_repository=ResultRepository(storage),
        storage_repository=storage,
        voice_repository=VoiceRepository(tmp_path / "voices"),
    )
    return facade, storage


def _preparar_job(facade, storage, job_id="job-1", participants=None):
    storage.save_audio(job_id, b"fake-wav-bytes", "reuniao.wav")
    facade._jobs.create(
        job_id=job_id,
        title="Reunião de teste",
        participants=participants if participants is not None else [Participant(id="p1", name="Leandro")],
        expected_speaker_count=None,
    )


def _transcricao_fake() -> TranscriptionResult:
    return TranscriptionResult(
        metadata=TranscriptionMetadata(
            audio_file="reuniao.wav",
            generated_at="2026-01-01T00:00:00Z",
            model="turbo",
            language="pt",
            duration_seconds=2.0,
            sample_rate=16000,
        ),
        segments=[],
    )


def _diarizacao_fake() -> DiarizationResult:
    return DiarizationResult(
        segments=[DiarizedSegment(id=0, cluster="SPEAKER_00", start=0.0, end=2.0, text="Bom dia.")]
    )


def _segments_fake():
    return [
        Segment(
            id="seg_0001",
            cluster="SPEAKER_00",
            participant_id="p1",
            speaker="Leandro",
            identified=True,
            confidence=0.9,
            start=0.0,
            end=2.0,
            text="Bom dia.",
        )
    ]


def _mock_estagios_felizes(monkeypatch):
    monkeypatch.setattr(transcription_service, "transcribe", lambda audio_path, language=None: _transcricao_fake())
    monkeypatch.setattr(
        diarization_service,
        "diarizar",
        lambda audio_path, transcricao, expected_speaker_count=None, exact_speaker_count=False: _diarizacao_fake(),
    )
    monkeypatch.setattr(
        voice_service, "aplicar_biometria", lambda audio_path, diarizacao, banco, nomes=None, **kw: _segments_fake()
    )
    monkeypatch.setattr(question_service, "summarize_meeting", lambda formatter: "resumo qualquer")
    monkeypatch.setattr(
        question_service,
        "extract_explicit_questions",
        lambda formatter: [
            Question(
                id="P1",
                type=QuestionType.EXPLICIT,
                text="Qual é o prazo?",
                participant_id="p1",
                speaker="Leandro",
                time=0.0,
                source_segment_ids=["seg_0001"],
            )
        ],
    )
    monkeypatch.setattr(
        question_service,
        "extract_implicit_questions",
        lambda formatter, summary: [
            Question(id="I1", type=QuestionType.IMPLICIT, text="Pergunta implícita?", source_segment_ids=[])
        ],
    )


# ---------------------------------------------------------------------------
# Caminho feliz: estados percorridos na ordem certa + resultado persistido
# ---------------------------------------------------------------------------


def test_pipeline_completo_persiste_resultado_e_marca_done(tmp_path, monkeypatch):
    from app.config import get_settings

    facade, storage = _nova_facade(tmp_path)
    _preparar_job(facade, storage)
    _mock_estagios_felizes(monkeypatch)

    # Caminho feliz completo (explícitas + implícitas combinadas) — precisa
    # da etapa de implícitas ligada explicitamente, já que o default passou
    # a ser desligado (ENABLE_IMPLICIT_QUESTIONS=false, ver docs/PENDENCIAS.md).
    monkeypatch.setenv("ENABLE_IMPLICIT_QUESTIONS", "true")
    get_settings.cache_clear()
    try:
        facade.executar("job-1")
    finally:
        get_settings.cache_clear()

    job = facade._jobs.get("job-1")
    assert job.status == JobStatusValue.DONE
    assert job.error is None

    resultado = facade._results.load("job-1")
    assert resultado is not None
    assert resultado.job_id == "job-1"
    assert len(resultado.segments) == 1
    assert len(resultado.questions) == 2
    assert resultado.segments[0].participant_id == "p1"
    assert resultado.metadata.stub is False


def test_pipeline_percorre_estagios_na_ordem_correta(tmp_path, monkeypatch):
    from app.config import get_settings

    facade, storage = _nova_facade(tmp_path)
    _preparar_job(facade, storage)

    # Testa a ordem completa dos 6 estágios internos, incluindo summarize/
    # extract_implicit — precisa da flag ligada (default agora é desligado).
    monkeypatch.setenv("ENABLE_IMPLICIT_QUESTIONS", "true")
    get_settings.cache_clear()

    sequencia = []

    def _snapshot(nome):
        sequencia.append((nome, facade._jobs.get("job-1").status))

    def fake_transcribe(audio_path, language=None):
        _snapshot("transcribe")
        return _transcricao_fake()

    def fake_diarizar(audio_path, transcricao, expected_speaker_count=None, exact_speaker_count=False):
        _snapshot("diarizar")
        return _diarizacao_fake()

    def fake_aplicar_biometria(audio_path, diarizacao, banco, nomes=None, **kw):
        _snapshot("aplicar_biometria")
        return _segments_fake()

    def fake_summarize(formatter):
        _snapshot("summarize")
        return "resumo"

    def fake_extract_explicit(formatter):
        _snapshot("extract_explicit")
        return []

    def fake_extract_implicit(formatter, summary):
        _snapshot("extract_implicit")
        return []

    monkeypatch.setattr(transcription_service, "transcribe", fake_transcribe)
    monkeypatch.setattr(diarization_service, "diarizar", fake_diarizar)
    monkeypatch.setattr(voice_service, "aplicar_biometria", fake_aplicar_biometria)
    monkeypatch.setattr(question_service, "summarize_meeting", fake_summarize)
    monkeypatch.setattr(question_service, "extract_explicit_questions", fake_extract_explicit)
    monkeypatch.setattr(question_service, "extract_implicit_questions", fake_extract_implicit)

    try:
        facade.executar("job-1")
    finally:
        get_settings.cache_clear()

    nomes_estagios = [nome for nome, _ in sequencia]
    status_por_estagio = [status for _, status in sequencia]

    assert nomes_estagios == [
        "transcribe",
        "diarizar",
        "aplicar_biometria",
        "summarize",
        "extract_explicit",
        "extract_implicit",
    ]
    # status já estava atualizado ANTES de cada chamada de estágio
    assert status_por_estagio == [
        JobStatusValue.TRANSCRIBING,
        JobStatusValue.DIARIZING,
        JobStatusValue.IDENTIFYING,
        JobStatusValue.SUMMARIZING,
        JobStatusValue.EXTRACTING,
        JobStatusValue.EXTRACTING,
    ]
    assert facade._jobs.get("job-1").status == JobStatusValue.DONE


def test_pipeline_chama_refinamento_so_quando_flag_ativa(tmp_path, monkeypatch):
    import os

    facade, storage = _nova_facade(tmp_path)
    _preparar_job(facade, storage)
    _mock_estagios_felizes(monkeypatch)

    chamado = {"refine": False}

    def fake_refine(perguntas, formatter):
        chamado["refine"] = True
        return [Question(id="I1", type=QuestionType.IMPLICIT, text="refinada", source_segment_ids=[])]

    monkeypatch.setattr(question_service, "refine_implicit_questions", fake_refine)

    # Refinamento só é alcançado quando a etapa de implícitas está ligada —
    # sem isso, extract_implicit_questions nem roda (default agora é
    # desligado, ver docs/PENDENCIAS.md).
    monkeypatch.setenv("ENABLE_IMPLICIT_QUESTIONS", "true")
    monkeypatch.setenv("ENABLE_IMPLICIT_REFINEMENT", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        facade.executar("job-1")
        assert chamado["refine"] is False

        monkeypatch.setenv("ENABLE_IMPLICIT_REFINEMENT", "true")
        get_settings.cache_clear()
        _preparar_job(facade, storage, job_id="job-2")
        facade.executar("job-2")
        assert chamado["refine"] is True

        resultado = facade._results.load("job-2")
        assert any(q.text == "refinada" for q in resultado.questions)
    finally:
        get_settings.cache_clear()


def test_pipeline_pula_etapa_implicita_quando_flag_desligada(tmp_path, monkeypatch):
    """ENABLE_IMPLICIT_QUESTIONS=false (default): não chama summarize_meeting
    nem extract_implicit_questions — pipeline completa normalmente com DONE e
    o resultado só tem perguntas explícitas, sem itens vazios/placeholder no
    lugar das implícitas. Ver docs/PENDENCIAS.md."""
    from app.config import get_settings

    facade, storage = _nova_facade(tmp_path)
    _preparar_job(facade, storage)

    chamado = {"summarize": False, "extract_implicit": False}

    def fake_summarize_nao_deveria_ser_chamado(formatter):
        chamado["summarize"] = True
        return "resumo"

    def fake_extract_implicit_nao_deveria_ser_chamado(formatter, summary):
        chamado["extract_implicit"] = True
        return [Question(id="I1", type=QuestionType.IMPLICIT, text="não deveria existir", source_segment_ids=[])]

    monkeypatch.setattr(transcription_service, "transcribe", lambda audio_path, language=None: _transcricao_fake())
    monkeypatch.setattr(
        diarization_service,
        "diarizar",
        lambda audio_path, transcricao, expected_speaker_count=None, exact_speaker_count=False: _diarizacao_fake(),
    )
    monkeypatch.setattr(
        voice_service, "aplicar_biometria", lambda audio_path, diarizacao, banco, nomes=None, **kw: _segments_fake()
    )
    monkeypatch.setattr(question_service, "summarize_meeting", fake_summarize_nao_deveria_ser_chamado)
    monkeypatch.setattr(
        question_service,
        "extract_explicit_questions",
        lambda formatter: [
            Question(
                id="P1",
                type=QuestionType.EXPLICIT,
                text="Qual é o prazo?",
                participant_id="p1",
                speaker="Leandro",
                time=0.0,
                source_segment_ids=["seg_0001"],
            )
        ],
    )
    monkeypatch.setattr(question_service, "extract_implicit_questions", fake_extract_implicit_nao_deveria_ser_chamado)

    monkeypatch.setenv("ENABLE_IMPLICIT_QUESTIONS", "false")
    get_settings.cache_clear()
    try:
        facade.executar("job-1")
    finally:
        get_settings.cache_clear()

    assert chamado["summarize"] is False
    assert chamado["extract_implicit"] is False

    job = facade._jobs.get("job-1")
    assert job.status == JobStatusValue.DONE
    assert job.error is None

    resultado = facade._results.load("job-1")
    assert resultado is not None
    assert len(resultado.questions) == 1
    assert all(q.type == QuestionType.EXPLICIT for q in resultado.questions)


# ---------------------------------------------------------------------------
# Erros: nenhum resultado fictício, job vai para error com code/message
# ---------------------------------------------------------------------------


def test_erro_na_transcricao_marca_job_como_error_sem_resultado(tmp_path, monkeypatch):
    facade, storage = _nova_facade(tmp_path)
    _preparar_job(facade, storage)

    def fake_transcribe_falha(audio_path, language=None):
        raise RuntimeError("modelo indisponível")

    monkeypatch.setattr(transcription_service, "transcribe", fake_transcribe_falha)

    facade.executar("job-1")

    job = facade._jobs.get("job-1")
    assert job.status == JobStatusValue.ERROR
    assert job.error.code == "TRANSCRIPTION_ERROR"
    assert "modelo indisponível" in job.error.message
    assert facade._results.load("job-1") is None


def test_erro_na_diarizacao_marca_job_como_error(tmp_path, monkeypatch):
    facade, storage = _nova_facade(tmp_path)
    _preparar_job(facade, storage)

    monkeypatch.setattr(transcription_service, "transcribe", lambda audio_path, language=None: _transcricao_fake())

    def fake_diarizar_falha(audio_path, transcricao, expected_speaker_count=None, exact_speaker_count=False):
        raise RuntimeError("HF_TOKEN ausente")

    monkeypatch.setattr(diarization_service, "diarizar", fake_diarizar_falha)

    facade.executar("job-1")

    job = facade._jobs.get("job-1")
    assert job.status == JobStatusValue.ERROR
    assert job.error.code == "DIARIZATION_ERROR"
    assert facade._results.load("job-1") is None


def test_erro_na_extracao_marca_job_como_error(tmp_path, monkeypatch):
    facade, storage = _nova_facade(tmp_path)
    _preparar_job(facade, storage)
    _mock_estagios_felizes(monkeypatch)

    def fake_extract_explicit_falha(formatter):
        raise ValueError("JSON inválido do LLM")

    monkeypatch.setattr(question_service, "extract_explicit_questions", fake_extract_explicit_falha)

    facade.executar("job-1")

    job = facade._jobs.get("job-1")
    assert job.status == JobStatusValue.ERROR
    assert job.error.code == "EXTRACTION_ERROR"
    assert facade._results.load("job-1") is None


def test_job_sem_audio_marca_erro(tmp_path):
    facade, storage = _nova_facade(tmp_path)
    facade._jobs.create(job_id="job-sem-audio", title=None, participants=[], expected_speaker_count=None)

    facade.executar("job-sem-audio")

    job = facade._jobs.get("job-sem-audio")
    assert job.status == JobStatusValue.ERROR
    assert job.error.code == "AUDIO_NAO_ENCONTRADO"


def test_executar_job_inexistente_nao_lanca_excecao(tmp_path):
    facade, _storage = _nova_facade(tmp_path)
    facade.executar("nao-existe")  # não deve lançar


# ---------------------------------------------------------------------------
# banco/nomes: só entra no banco quem tem perfil de voz; nomes vêm do job
# ---------------------------------------------------------------------------


def test_carregar_banco_so_inclui_quem_tem_perfil_de_voz(tmp_path):
    facade, _storage = _nova_facade(tmp_path)
    facade._voices.save_profile(
        participant_id="p1", embedding=torch.tensor([1.0, 0.0]), model_version="v1", sample_count=1
    )

    participantes = [Participant(id="p1", name="Leandro"), Participant(id="p2", name="Maria")]
    banco, nomes = facade._carregar_banco_e_nomes(participantes)

    assert set(banco.keys()) == {"p1"}
    assert nomes == {"p1": "Leandro", "p2": "Maria"}
