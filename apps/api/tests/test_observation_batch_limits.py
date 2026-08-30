import pytest
from pydantic import ValidationError

from app.v1.schemas import (
    MAX_OFFICIAL_OBSERVATION_PROVIDERS,
    MAX_OFFICIAL_OBSERVATION_QUESTIONS,
    MAX_OFFICIAL_OBSERVATION_REPEATS,
    OfficialApiObservationBatchCreate,
)


def test_manual_observation_batch_accepts_5_by_10_by_100_matrix() -> None:
    payload = OfficialApiObservationBatchCreate(
        provider_ids=list(range(1, 6)),
        question_plan_ids=list(range(1, 11)),
        repeat_count=100,
    )

    assert MAX_OFFICIAL_OBSERVATION_PROVIDERS == 5
    assert MAX_OFFICIAL_OBSERVATION_QUESTIONS == 10
    assert MAX_OFFICIAL_OBSERVATION_REPEATS == 100
    assert len(payload.provider_ids) * len(payload.question_plan_ids) * payload.repeat_count == 5000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_ids", list(range(1, 7))),
        ("question_plan_ids", list(range(1, 12))),
        ("repeat_count", 101),
    ],
)
def test_manual_observation_batch_rejects_values_above_limits(
    field: str,
    value: object,
) -> None:
    payload = {
        "provider_ids": [1],
        "question_plan_ids": [1],
        "repeat_count": 1,
        field: value,
    }

    with pytest.raises(ValidationError):
        OfficialApiObservationBatchCreate(**payload)


@pytest.mark.parametrize("field", ["provider_ids", "question_plan_ids"])
def test_manual_observation_batch_still_rejects_duplicate_ids(field: str) -> None:
    payload = {
        "provider_ids": [1],
        "question_plan_ids": [1],
        "repeat_count": 1,
        field: [1, 1],
    }

    with pytest.raises(ValidationError):
        OfficialApiObservationBatchCreate(**payload)
