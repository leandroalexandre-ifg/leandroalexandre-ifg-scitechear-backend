from app.models.result import MeetingResult, Question, QuestionType, ResultMetadata, Segment
from app.repositories.result_repository import ResultRepository
from app.repositories.storage_repository import StorageRepository


def test_save_e_load_roundtrip(tmp_path):
    storage = StorageRepository(tmp_path)
    repo = ResultRepository(storage)

    resultado = MeetingResult(
        job_id="job-1",
        segments=[
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
        ],
        questions=[
            Question(id="I1", type=QuestionType.IMPLICIT, text="Pergunta implícita?", source_segment_ids=[])
        ],
        metadata=ResultMetadata(stub=False),
    )

    repo.save(resultado)
    carregado = repo.load("job-1")

    assert carregado is not None
    assert carregado.job_id == "job-1"
    assert carregado.segments[0].participant_id == "p1"
    assert carregado.questions[0].type == QuestionType.IMPLICIT


def test_load_inexistente_retorna_none(tmp_path):
    storage = StorageRepository(tmp_path)
    repo = ResultRepository(storage)
    assert repo.load("nao-existe") is None
