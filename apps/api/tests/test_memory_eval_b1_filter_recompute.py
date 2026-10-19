"""필터 재계산 — 지식 범위 필터가 그 턴에 무엇을 뺐는지를 스키마 없이 하네스가 다시 계산한다. 서버의 판정 함수(장면 인물 집합과
아는 사람 판정)를 그대로 불러 같은 입력(커서 이하 사실 행 · 이번 사용자 메시지 · 직전 응답의 스캔 글 · 이름)으로 계산하므로,
필터를 켠 갈래에서 턴 기록에 실린 사실 행이 재계산의 "뺀 행"에 들어 있으면 재계산이 서버와 어긋난 것이다."""

import uuid
from datetime import UTC, datetime, timedelta

from api.chat.prompt_builder import PromptNames
from api.db.models import ChatMessage, ChatMessageRole
from api.db.models.chat import ChatMemoryFact
from factories import _make_memory_fact
from memory_eval import knowledge_recompute as kr

ROOM, SNAP = uuid.uuid4(), uuid.uuid4()


def _fact(key: str, known_by: list[str] | None, subject: str = "유나", **extra: object) -> ChatMemoryFact:
    return _make_memory_fact(
        ROOM, SNAP, id=uuid.uuid4(), kind="fact", subject=subject, object=None, attribute=key,
        fact_key=f"fact|{subject}|{key}", value="값", known_by=known_by, **extra,
    )  # fmt: skip


def _msg(role: ChatMessageRole, content: str, seconds: int) -> ChatMessage:
    at = datetime(2026, 10, 16, tzinfo=UTC) + timedelta(seconds=seconds)
    return ChatMessage(id=uuid.uuid4(), chat_room_id=ROOM, role=role, content=content, created_at=at)


def test_recompute_reports_dropped_and_kept_secret_rows_with_the_names_found_in_the_scene() -> None:
    told_taemin = _fact("숨긴 일", ["오태민"])
    told_jia = _fact("다른 비밀", ["지아"])
    told_user_only = _fact("사용자만 아는 일", ["나"])
    public = _fact("좋아하는 것", None)
    history = [
        _msg(ChatMessageRole.ASSISTANT, "오프닝", 0),
        _msg(ChatMessageRole.USER, "앞 질문", 1),
        _msg(ChatMessageRole.ASSISTANT, "지아는 아직 오지 않았다.", 2),
    ]
    out = kr.recompute_turn(
        [told_taemin, told_jia, told_user_only, public], history=history, user_content="오태민한테서 들었어?",
        names=PromptNames(persona_name="나", char_name=None), user_label="사용자", ignore_quoted_reply_names=False,
    )  # fmt: skip
    assert out["scenePeople"] == ["오태민", "지아"]
    assert out["candidates"] == 4
    assert out["droppedSecret"] == [str(told_user_only.id)]
    assert out["keptSecret"] == [
        {"factId": str(told_taemin.id), "knownInScene": ["오태민"]},
        {"factId": str(told_jia.id), "knownInScene": ["지아"]},
    ]


def test_scene_reads_only_the_previous_response_not_older_turns() -> None:
    secret = _fact("숨긴 일", ["지아"])
    history = [
        _msg(ChatMessageRole.ASSISTANT, "오프닝", 0),
        _msg(ChatMessageRole.USER, "첫 질문", 1),
        _msg(ChatMessageRole.ASSISTANT, "지아가 웃었다.", 2),
        _msg(ChatMessageRole.USER, "다음", 3),
        _msg(ChatMessageRole.ASSISTANT, "아무도 없다.", 4),
    ]
    out = kr.recompute_turn(
        [secret], history=history, user_content="무슨 일 있었어?", names=PromptNames(persona_name=None, char_name=None),
        user_label="사용자", ignore_quoted_reply_names=False,
    )  # fmt: skip
    assert out["droppedSecret"] == [str(secret.id)]


def test_probe_history_appends_the_setup_turns_before_the_question() -> None:
    base = [_msg(ChatMessageRole.ASSISTANT, "오프닝", 0)]
    history, question = kr.probe_history(
        base, [{"user": "지아를 부른다", "reply": "지아가 들어왔다."}, {"user": "그 일 말해 줘", "reply": "..."}]
    )
    assert question == "그 일 말해 줘"
    assert [(m.role, m.content) for m in history[1:]] == [
        (ChatMessageRole.USER, "지아를 부른다"),
        (ChatMessageRole.ASSISTANT, "지아가 들어왔다."),
    ]
    assert history[1].created_at > base[0].created_at


def test_recorded_rows_inside_the_dropped_set_mean_the_recompute_disagrees_when_the_filter_is_on() -> None:
    result = {"droppedSecret": ["d1"], "keptSecret": [{"factId": "k1", "knownInScene": ["x"]}]}
    ok = kr.compare_recorded(result, [{"factId": "k1"}, {"factId": "p1"}], filter_on=True)
    assert ok == {"recordedFactIds": ["k1", "p1"], "recordedDropped": [], "consistent": True}
    bad = kr.compare_recorded(result, [{"factId": "d1"}], filter_on=True)
    assert bad["recordedDropped"] == ["d1"] and bad["consistent"] is False
    # 필터를 끈 갈래에서는 "뺐을 행"이 실려도 어긋남이 아니다 — 공변량일 뿐이다.
    assert kr.compare_recorded(result, [{"factId": "d1"}], filter_on=False)["consistent"] is True
    assert kr.compare_recorded(result, None, filter_on=True)["consistent"] is None
