"""장면 인물 집합과 지식 범위 필터 — 아는 사람이 이번 장면에 없는 비밀 사실을 사실 섹션 후보에서 뺀다(DB·LLM 없음).

규칙(결과를 보기 전에 적었다):
- 방 이름 = 방 사실 행의 주어·관계 대상·말한 사람·아는 사람 원소 + 호출부가 더 주는 이름(매 턴 조립은 주지 않는다 — 판정은
  아는 사람 원소로만 하고 그 원소는 이미 행에서 들어온다). 사실 키와 같은 정규화를 하고, 2자 미만은 버리고, 사용자 표기는 뺀다.
- 사용자 표기 = 대화 프로필 이름(있으면)·대화 줄 라벨·`{{user}}` 대체어·추출 지시문이 사용자를 부르는 낱말. 프로필 이름이
  없는 방에서 추출이 사용자를 이 중 어느 것으로 적어도 사용자로 본다. 생성 모델이 연기하는 쪽은 사용자가 아니라서 사용자의
  앎은 누출 위험이 아니고, 진행자가 사용자를 이름으로 부르는 일이 흔해 사용자를 세면 그런 턴마다 비밀이 남는다.
- 장면 인물 = 방 이름 중 정규화한 이번 턴 사용자 메시지나 직전 응답에 부분 문자열로 나오는 것(조사가 몇 겹 붙어도 잡힌다).
- 아는 사람이 정해진 행은 그 이름 중 하나가 장면 인물일 때만 남는다. 아는 사람이 정해지지 않은 행(공개·불명)은 늘 남는다."""

import unicodedata
from collections.abc import Sequence

from api.chat.memory_knowledge import known_in_scene, room_names, scene_people, user_names
from api.content.author_macros import FALLBACK_USER_NAME
from api.db.models import ChatMemoryFact

PERSONA = "하늘"
LABEL = "사용자"


def _row(subject: str = "유나", *, known_by: list[str] | None = None, **extra: object) -> ChatMemoryFact:
    """세션 없이 만든 사실 행 — 이 모듈이 읽는 칸(종류·주어·대상·말한 사람·아는 사람)만 채운다."""
    fields: dict[str, object] = {"kind": "fact", "subject": subject, "known_by": known_by, **extra}
    return ChatMemoryFact(**fields)


def _kept(
    row: ChatMemoryFact,
    user_text: str,
    previous_response: str = "",
    *,
    persona: str | None = PERSONA,
    extra: Sequence[str] = ("민수",),
) -> bool:
    users = user_names(persona, LABEL)
    scene = scene_people(room_names([row], extra, users=users), (user_text, previous_response))
    return known_in_scene(row, scene)


# 유나가 사용자(하늘)에게만 털어놓은 비밀.
_TOLD_THE_USER = _row(known_by=["유나", PERSONA])


def test_secret_told_only_to_the_user_drops_when_only_someone_else_is_named() -> None:
    """민수만 나온 턴 — 진행자가 사용자를 이름으로 불러도 유나의 비밀은 빠진다."""
    assert not _kept(_TOLD_THE_USER, "민수는 뭐 해?", "하늘 씨, 민수가 문을 열고 들어왔다.")


def test_secret_stays_when_someone_who_knows_is_named() -> None:
    assert _kept(_TOLD_THE_USER, "유나는 어디 갔어?")
    # 직전 응답에만 나와도 장면 인물이다.
    assert _kept(_TOLD_THE_USER, "그래서?", "유나가 고개를 들었다.")


def test_secret_drops_on_a_turn_without_any_name() -> None:
    assert not _kept(_TOLD_THE_USER, "오늘 날씨 좋다", "바람이 분다.")


def test_row_without_known_by_always_stays() -> None:
    assert _kept(_row(), "오늘 날씨 좋다", "바람이 분다.")


def test_name_with_stacked_particles_is_in_the_scene() -> None:
    """조사가 "유나한테서" 처럼 두 겹 붙어도 부분 문자열로 잡힌다. 대소문자·NFD 자모도 사실 키와 같은 정규화로 맞춘다."""
    assert _kept(_TOLD_THE_USER, "유나한테서 들었어")
    assert _kept(_row("Yuna", known_by=["Yuna"]), "I heard it from YUNA's sister")
    assert scene_people(["유나"], ["유나한테서"]) == {"유나"}
    assert scene_people(["유나"], [unicodedata.normalize("NFD", "유나야")]) == {"유나"}


def test_one_char_names_are_ignored() -> None:
    """1자 이름은 방 이름에 들지 않는다 — 흔한 글자라 아무 턴에나 걸린다. 그 이름만 아는 비밀은 그 글자가 나와도 빠진다."""
    secret = _row("진", known_by=["진", PERSONA])
    assert "진" not in room_names([secret], ["진"], users=user_names(PERSONA, LABEL))
    assert not _kept(secret, "진이 웃었다", extra=("진",))


def test_user_name_in_the_dialogue_is_not_a_scene_person() -> None:
    """사용자 이름이 대사에 나와도 장면 인물이 아니다 — 사용자만 아는 비밀은 사용자가 불린 턴에도 빠진다."""
    users = user_names(PERSONA, LABEL)
    assert PERSONA not in room_names([_TOLD_THE_USER], [], users=users)
    assert scene_people(room_names([_TOLD_THE_USER], [], users=users), ["하늘아, 이리 와"]) == frozenset()
    assert not _kept(_row(known_by=[PERSONA]), "하늘아, 이리 와")


def test_room_without_a_profile_name_treats_every_user_form_as_the_user() -> None:
    """프로필 이름이 없으면 추출이 사용자를 라벨·`{{user}}` 대체어·지시문 낱말 중 하나로 적는다 — 어느 것이 대사에 나와도 그
    비밀을 아는 인물이 장면에 있다고 보지 않는다."""
    users = user_names(None, LABEL)
    assert {LABEL, FALLBACK_USER_NAME, "사용자 인물"} <= users
    for form in (LABEL, FALLBACK_USER_NAME, "사용자 인물"):
        secret = _row(known_by=["유나", form])
        assert not _kept(secret, f"{form}은 민수를 본다", f"{form}에게 민수가 다가온다.", persona=None)
        assert _kept(secret, "유나를 찾아", persona=None)


def test_room_names_come_from_every_name_field_and_the_extra_names() -> None:
    """주어·관계 대상·말한 사람·아는 사람 원소와 호출부 이름(미디어 북 인물·작품 이름)이 모두 출처다. 사실 행의 속성·값은 이름이
    아니다."""
    rows = [
        _row("유나", attribute="취미", value="테니스"),
        _row("민수", kind="relation", object="지아"),
        _row("태민", speaker="서진", known_by=["다은"]),
    ]
    assert room_names(rows, ["강현우", " Mina "], users=user_names(None, LABEL)) == {
        "유나",
        "민수",
        "지아",
        "태민",
        "서진",
        "다은",
        "강현우",
        "mina",
    }
