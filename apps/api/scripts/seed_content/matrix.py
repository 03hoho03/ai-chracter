"""다양성 매트릭스 — 30개 스토리 슬롯의 좌표 스펙.

`data/diversity_matrix.json` 은 `tasks/prd-genre-seed-content.md` §7 을 기계가 읽는 형태로
전사한 것이다. 콘셉트(제목·한줄·세계관·좌표·스탯 축·target)는 여기서 확정이고, 배치
생성기(US-013)는 이 좌표를 입력으로 받아 **본문만** 채운다 — 생성기가 콘셉트를 새로
발명하지 않아야 같은 장르 3개의 겹침을 생성 후가 아니라 생성 전에 막을 수 있다.

`load_matrix()` 는 읽으면서 항상 `validate_matrix()` 를 거치므로, 슬롯을 고치다 §7 의
분포(축마다 10/10/10)나 "같은 장르 3슬롯은 최소 4개 축이 다르다" 규칙을 깨면 파일을 읽는
순간 죽는다.
"""

import json
import uuid
from collections import Counter
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from api.core.schema import CamelModel

from .loader import DATA_DIR, SeedContentError

MATRIX_PATH = DATA_DIR / "diversity_matrix.json"

# §7 이 정한 규모: 장르 10종 × 슬롯 3개. 축 값도 3종씩이라 값 하나당 정확히 10슬롯이다.
SLOTS_PER_GENRE = 3
SLOTS_PER_AXIS_VALUE = 10
MIN_AXIS_DIFFERENCE = 4

# 이미지에서 역산해 손으로 집필한 메이저 슬롯(US-007~009). 생성기 대상에서 제외된다.
MAJOR_SLUG = "romance-3rdloop"

Tone = Literal["순애", "피폐", "격정"]
Relation = Literal["집착", "다각", "혐관"]
Verb = Literal["공략", "추리", "생존"]
Space = Literal["현대", "이세계", "밀실"]
EndingPressure = Literal["해피", "다중", "배드"]
Target = Literal["female", "male", "all"]


class MatrixAxes(CamelModel):
    """§6 의 다양성 축 5종. §7 의 괄호 주석(`밀실(학교)` 등)은 대표값으로 정규화했다."""

    tone: Tone
    relation: Relation
    verb: Verb
    space: Space
    ending_pressure: EndingPressure

    def as_tuple(self) -> tuple[str, str, str, str, str]:
        return (self.tone, self.relation, self.verb, self.space, self.ending_pressure)


class MatrixSlot(CamelModel):
    slug: str
    genre: str
    genre_id: uuid.UUID
    slot: int
    title: str
    one_liner: str
    setting: str
    target: Target
    axes: MatrixAxes
    stats: list[str]
    starting_setups: list[str]
    forbidden: list[str]
    hand_written: bool = False


def load_matrix(path: Path = MATRIX_PATH) -> list[MatrixSlot]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedContentError(f"{path.name}: JSON 을 읽지 못했다 — {exc}") from exc
    if not isinstance(raw, list):
        raise SeedContentError(f"{path.name}: 최상위가 JSON 배열이 아니다")
    try:
        slots = [MatrixSlot.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise SeedContentError(f"{path.name}: MatrixSlot 스키마에 맞지 않는다 — {exc}") from exc
    validate_matrix(slots)
    return slots


def validate_matrix(slots: list[MatrixSlot]) -> None:
    """§7 이 스스로 주장하는 성질들을 실제로 만족하는지 본다 — 위반이면 `SeedContentError`."""
    _validate_slugs(slots)
    _validate_genre_slots(slots)
    _validate_axis_differences(slots)
    _validate_distribution(slots)


def _validate_slugs(slots: list[MatrixSlot]) -> None:
    duplicates = sorted(slug for slug, count in Counter(s.slug for s in slots).items() if count > 1)
    if duplicates:
        raise SeedContentError(f"slug 가 중복됐다: {duplicates}")

    hand_written = sorted(s.slug for s in slots if s.hand_written)
    if hand_written != [MAJOR_SLUG]:
        raise SeedContentError(
            f"handWritten 슬롯은 메이저 '{MAJOR_SLUG}' 하나뿐이어야 한다 — 실제: {hand_written}"
        )


def _validate_genre_slots(slots: list[MatrixSlot]) -> None:
    for genre, group in _by_genre(slots).items():
        if len(group) != SLOTS_PER_GENRE:
            raise SeedContentError(f"장르 '{genre}' 의 슬롯이 {len(group)}개다 — {SLOTS_PER_GENRE}개여야 한다")
        numbers = sorted(s.slot for s in group)
        if numbers != list(range(1, SLOTS_PER_GENRE + 1)):
            raise SeedContentError(f"장르 '{genre}' 의 slot 번호가 {numbers}다 — 1..{SLOTS_PER_GENRE} 여야 한다")
        genre_ids = {s.genre_id for s in group}
        if len(genre_ids) != 1:
            raise SeedContentError(f"장르 '{genre}' 안에서 genreId 가 갈린다: {sorted(map(str, genre_ids))}")


def _validate_axis_differences(slots: list[MatrixSlot]) -> None:
    """같은 장르 3슬롯은 5개 축 중 최소 4개가 서로 달라야 한다(§6 규칙)."""
    for genre, group in _by_genre(slots).items():
        for left, right in combinations(sorted(group, key=lambda s: s.slot), 2):
            different = sum(
                1 for a, b in zip(left.axes.as_tuple(), right.axes.as_tuple(), strict=True) if a != b
            )
            if different < MIN_AXIS_DIFFERENCE:
                raise SeedContentError(
                    f"장르 '{genre}' 의 {left.slug} ↔ {right.slug} 가 축 {different}개만 다르다 "
                    f"— {MIN_AXIS_DIFFERENCE}개 이상이어야 한다 "
                    f"({left.axes.as_tuple()} vs {right.axes.as_tuple()})"
                )


def _validate_distribution(slots: list[MatrixSlot]) -> None:
    """축 값별 전체 분포가 §7 말미의 검증 표(전부 10/10/10)와 일치하는지 본다."""
    axis_values: dict[str, Sequence[str]] = {
        "tone": [s.axes.tone for s in slots],
        "relation": [s.axes.relation for s in slots],
        "verb": [s.axes.verb for s in slots],
        "space": [s.axes.space for s in slots],
        "endingPressure": [s.axes.ending_pressure for s in slots],
        "target": [s.target for s in slots],
    }
    for axis, values in axis_values.items():
        counts = Counter(values)
        off = {value: count for value, count in counts.items() if count != SLOTS_PER_AXIS_VALUE}
        if off or len(counts) != 3:
            raise SeedContentError(
                f"축 '{axis}' 의 분포가 {dict(sorted(counts.items()))} 다 "
                f"— 값 3종이 각각 {SLOTS_PER_AXIS_VALUE}개여야 한다"
            )


def _by_genre(slots: list[MatrixSlot]) -> dict[str, list[MatrixSlot]]:
    grouped: dict[str, list[MatrixSlot]] = {}
    for slot in slots:
        grouped.setdefault(slot.genre, []).append(slot)
    return grouped
