"""장면 인물 집합과 지식 범위 필터 — 아는 사람이 이번 장면에 없는 비밀 사실을 사실 섹션 후보에서 뺀다(DB·LLM 없음).

규칙(결과를 보기 전에 적었다):
- 방 이름 = 방 사실 행의 주어·관계 대상·말한 사람·아는 사람 원소 + 호출부가 더 주는 이름(사실 섹션은 주지 않는다 — 판정은
  아는 사람 원소로만 하고 그 원소는 이미 행에서 들어온다. 회상의 가림은 후보 장면 행의 아는 사람 원소를 더 준다 — 사실 행에 없는
  이름이 장면 칸에만 있을 수 있다). 사실 키와 같은 정규화를 하고, 2자 미만은 버리고, 사용자 표기는 뺀다.
- 사용자 표기 = 대화 프로필 이름(있으면)·대화 줄 라벨·`{{user}}` 대체어·추출 지시문이 사용자를 부르는 낱말. 프로필 이름이
  없는 방에서 추출이 사용자를 이 중 어느 것으로 적어도 사용자로 본다. 생성 모델이 연기하는 쪽은 사용자가 아니라서 사용자의
  앎은 누출 위험이 아니고, 진행자가 사용자를 이름으로 부르는 일이 흔해 사용자를 세면 그런 턴마다 비밀이 남는다.
- 장면 인물 = 방 이름 중 정규화한 이번 턴 사용자 메시지나 직전 응답에 부분 문자열로 나오는 것(조사가 몇 겹 붙어도 잡힌다).
- 지식 범위 필터 스위치를 켠 턴(`KnowledgeScope` 가 그렇게 받는다)은 직전 응답에서 대사 따옴표(`"…"`·`“…”`·`「…」`·`『…』`)
  안에서만 나온 이름을 장면 인물로 세지 않는다 — 인물이 말로 꺼낸 이름은 그 사람이 장면에 있다는 뜻이 아니다. 사용자 메시지는
  따옴표 안이어도 세고, 직전 응답 서술(따옴표 밖)에 한 번이라도 나오면 센다. 짝이 맞지 않는 따옴표는 대사로 보지 않는다.
- 아는 사람이 정해진 행은 그 이름 중 하나가 장면 인물일 때만 남는다. 아는 사람이 정해지지 않은 행(공개·불명)은 늘 남는다. 사실
  행과 장면 행이 아는 사람 목록 하나로 같은 판정을 쓴다."""

import unicodedata
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from api.chat import memory_fact_section
from api.chat.memory_knowledge import (
    KnowledgeScope,
    hidden_fact_keys,
    hidden_ranges,
    known_in_scene,
    latest_by_key,
    overlaps,
    room_names,
    scene_for_turn,
    scene_people,
    user_names,
)
from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import PromptNames
from api.content.author_macros import FALLBACK_USER_NAME
from api.db.models import ChatMemoryFact, ChatMessage, ChatMessageRole

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
    return known_in_scene(row.known_by, scene)


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


# --- 회상 줄의 비밀 장면 ---------------------------------------------------------------------
# 회상은 장면 행 자신의 아는 사람 칸과 함께 사실 행에서도 비밀을 끌어낸다 — 키별 최신 행이 위 필터를 지나지 못하는 키(가려진 키)의
# 어느 행과든 근거 메시지 범위가 겹치는(양 끝 포함) 장면을 그 턴 회상에서 뺀다. 키의 최신 행이 공개면 옛 행이 비밀이었어도
# 가리지 않는다.

_T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _key(minute: int) -> MessageKey:
    """분 단위로 늘어나는 메시지 키(같은 분이면 id 로 갈린다 — 여기서는 분마다 id 하나)."""
    return (_T0 + timedelta(minutes=minute), uuid.UUID(int=minute))


def _fact(value: str, *, known_by: list[str] | None, span: tuple[int, int], status: str = "confirmed") -> ChatMemoryFact:
    """유나의 오디션 사실 한 행 — 근거는 `span` 분의 메시지 범위."""
    start, end = _key(span[0]), _key(span[1])
    return _row(
        known_by=known_by,
        attribute="오디션",
        fact_key="fact|유나|오디션",
        value=value,
        truth_status=status,
        start_created_at=start[0],
        start_message_id=start[1],
        end_created_at=end[0],
        end_message_id=end[1],
    )


def _span(start: int, end: int) -> tuple[MessageKey, MessageKey]:
    return (_key(start), _key(end))


def test_latest_secret_row_hides_every_row_of_its_key() -> None:
    """최신 행이 여전히 비밀이면 그 키의 옛 행(다른 범위)도 가린다 — 옛 행과만 겹치는 장면도 같은 비밀을 담는다."""
    rows = [_fact("겨울", known_by=None, span=(1, 2)), _fact("봄", known_by=["유나"], span=(10, 11))]
    assert hidden_fact_keys(rows, frozenset()) == {"fact|유나|오디션"}
    assert hidden_ranges(rows, frozenset()) == [_span(1, 2), _span(10, 11)]
    # 아는 사람이 장면에 있으면 가리지 않는다.
    assert hidden_ranges(rows, frozenset({"유나"})) == []


def test_latest_public_row_unhides_an_older_secret() -> None:
    """키의 지금 값이 공개면 옛 값이 비밀이었어도 가리지 않는다 — 판정은 키별 최신 행으로 한다."""
    rows = [_fact("겨울", known_by=["유나"], span=(1, 2)), _fact("봄", known_by=None, span=(10, 11))]
    assert hidden_ranges(rows, frozenset()) == []


def test_latest_by_key_decides_with_the_disproved_winner() -> None:
    """같은 값의 반증 행이 앞에 있으면 뒤의 주장보다 반증 행이 키의 승자다 — 그 반증 행이 공개면 가리지 않는다. 마지막 행만 보면
    비밀인 주장 행으로 가린다."""
    rows = [
        _fact("겨울", known_by=None, span=(1, 2), status="disproved"),
        _fact("겨울", known_by=["유나"], span=(10, 11), status="claimed"),
    ]
    assert hidden_ranges(rows, frozenset()) == []


@pytest.mark.parametrize(
    ("episode", "hit"),
    [
        pytest.param((3, 5), True, id="ends-on-the-fact-start"),
        pytest.param((7, 9), True, id="starts-on-the-fact-end"),
        pytest.param((5, 5), True, id="one-message-fact-inside"),
        pytest.param((4, 6), True, id="covers-the-fact"),
        pytest.param((1, 4), False, id="right-before"),
        pytest.param((8, 9), False, id="right-after"),
    ],
)
def test_overlap_counts_both_ends(episode: tuple[int, int], hit: bool) -> None:
    """사실 근거 5~7분. 한 메시지라도 닿으면 겹치고, 맞붙기만 하면 겹치지 않는다."""
    assert overlaps(_span(*episode), _span(5, 7)) is hit
    assert overlaps(_span(5, 7), _span(*episode)) is hit


def test_recall_hides_the_same_keys_the_fact_section_filter_drops() -> None:
    """같은 사실 행·같은 턴 글이면 사실 섹션의 지식 범위 필터가 빼는 키와 회상이 가리는 키가 같다 — 장면 인물은 같은 함수
    (`scene_for_turn`)로 센다."""
    rows = [
        _row("유나", known_by=["유나", PERSONA], fact_key="fact|유나|비밀", value="전학", attribute="비밀"),
        _row("민수", known_by=["민수"], fact_key="fact|민수|꿈", value="배우", attribute="꿈"),
        _row("지아", known_by=None, fact_key="fact|지아|취미", value="테니스", attribute="취미"),
    ]
    history = [
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="오프닝"),
        ChatMessage(role=ChatMessageRole.USER, content="안녕"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="민수가 하늘에게 손을 흔들었다."),
    ]
    names = PromptNames(persona_name=PERSONA, char_name=None)
    scope = KnowledgeScope(user_label=LABEL)
    keep = memory_fact_section._knowledge_filter(rows, scope, history=history, user_content="뭐 해?", names=names)
    scene = scene_for_turn(rows, scope, history=history, user_content="뭐 해?", names=names)

    dropped = {row.fact_key for _, row in latest_by_key(rows) if not keep(row)}
    assert dropped == {"fact|유나|비밀"}
    assert hidden_fact_keys(rows, scene) == dropped


# --- 장면 행의 아는 사람 칸과 직전 응답의 대사 ------------------------------------------------------


def test_known_by_judgment_takes_a_bare_name_list() -> None:
    """사실 행과 장면 행이 같은 판정을 쓰도록 아는 사람 목록만 받는다 — 목록이 없으면 남고, 원소 하나라도 장면 인물이면 남는다.
    원소는 사실 키와 같은 정규화로 맞춘다."""
    scene = frozenset({"민수"})
    assert known_in_scene(None, scene)
    assert known_in_scene(["유나", "민수"], scene)
    assert known_in_scene([" 민수 "], scene)
    assert not known_in_scene(["유나"], scene)
    assert not known_in_scene(["유나"], frozenset())
    # 사실 행은 자기 칸을 넘긴다.
    assert known_in_scene(_row(known_by=["민수"]).known_by, scene)
    assert not known_in_scene(_TOLD_THE_USER.known_by, scene)
    assert known_in_scene(_row().known_by, frozenset())


_NAMES = PromptNames(persona_name=PERSONA, char_name=None)


def _history_with(reply: str) -> list[ChatMessage]:
    return [
        ChatMessage(role=ChatMessageRole.ASSISTANT, content="오프닝"),
        ChatMessage(role=ChatMessageRole.USER, content="안녕"),
        ChatMessage(role=ChatMessageRole.ASSISTANT, content=reply),
    ]


def test_extra_names_join_the_room_names_but_user_forms_do_not() -> None:
    """사실 행이 하나도 없어도 호출부가 준 이름(회상 후보 장면의 아는 사람 원소)이 턴에 나오면 장면 인물이다. 사용자 표기는 더 줘도
    장면 인물이 아니다."""
    scope = KnowledgeScope(user_label=LABEL)
    history = _history_with("바람이 분다.")
    message = "유나랑 하늘이 왔어"

    assert scene_for_turn([], scope, history=history, user_content=message, names=_NAMES) == frozenset()
    assert scene_for_turn(
        [], scope, history=history, user_content=message, names=_NAMES, extra=["유나", PERSONA, "사용자 인물"]
    ) == {"유나"}


_BOTH = [_row("유나", known_by=["유나"]), _row("민수", known_by=["민수"])]


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param('"민수는 어디 갔어?" 유나가 물었다.', id="straight"),
        pytest.param("“민수는 어디 갔어?” 유나가 물었다.", id="curly"),
        pytest.param("「민수는 어디 갔어?」 유나가 물었다.", id="corner"),
        pytest.param("『민수는 어디 갔어?』 유나가 물었다.", id="white-corner"),
    ],
)
def test_name_only_inside_reply_dialogue_is_not_a_scene_person_when_the_filter_is_on(reply: str) -> None:
    """직전 응답에서 민수는 대사 안에만, 유나는 서술에 나온다. 필터를 켠 턴은 민수를 세지 않고, 끈 턴은 지금처럼 센다."""
    on = KnowledgeScope(user_label=LABEL, ignore_quoted_reply_names=True)
    off = KnowledgeScope(user_label=LABEL)
    history = _history_with(reply)

    assert scene_for_turn(_BOTH, on, history=history, user_content="그래서?", names=_NAMES) == {"유나"}
    assert scene_for_turn(_BOTH, off, history=history, user_content="그래서?", names=_NAMES) == {"유나", "민수"}


@pytest.mark.parametrize(
    ("user_content", "reply"),
    [
        pytest.param('"민수 어디 갔어?" 하고 물었다', "바람이 분다.", id="user-message-even-in-quotes"),
        pytest.param("그래서?", "“민수는 어디 갔어?” 유나가 민수를 찾았다.", id="also-in-the-narration"),
        pytest.param("그래서?", "“민수는 어디 갔어? 유나가 물었다.", id="unpaired-quote-is-not-dialogue"),
    ],
)
def test_name_in_the_user_message_or_the_reply_narration_still_counts(user_content: str, reply: str) -> None:
    on = KnowledgeScope(user_label=LABEL, ignore_quoted_reply_names=True)
    scene = scene_for_turn(_BOTH, on, history=_history_with(reply), user_content=user_content, names=_NAMES)
    assert "민수" in scene


def test_dropping_reply_dialogue_does_not_join_the_words_around_it() -> None:
    """대사를 지운 앞뒤 서술은 이어 붙이지 않는다 — 붙이면 경계를 걸친 가짜 이름이 생긴다."""
    on = KnowledgeScope(user_label=LABEL, ignore_quoted_reply_names=True)
    history = _history_with("유“아무 말”나무가 흔들렸다.")
    assert scene_for_turn(_BOTH, on, history=history, user_content="그래서?", names=_NAMES) == frozenset()
