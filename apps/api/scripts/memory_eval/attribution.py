"""출처 귀속 — 정답이 생성 프롬프트(서버 덤프)의 어느 자리에 실렸나: 기억 노트 · 요약 · 회상 · 원문 윈도 · 어디에도 없음.

앞선 장기 측정의 귀속 규칙을 따른다: 노트·요약은 그 턴의 기억 조회 전문에서 문자열 그대로 찾아 덤프에서 떼어 내고, 나머지를
원문 윈도로 본다. 문자열을 덤프에서 그대로 찾지 못하면 귀속하지 않는다(다른 판의 요약을 보고 있다는 뜻). 회상 섹션과 사실
섹션도 머리글부터 다음 빈 줄까지를 떼어 내 따로 센다. 머리글은 그 글자만으로 된 줄일 때만 머리글이다 — 사실 섹션 안내문이
회상 머리글 이름을 문장 속에서 부르므로, 첫 등장을 잡으면 사실 행이 회상 칸으로, 진짜 회상이 원문 창으로 밀린다. 사실 섹션이
옛 값(정정 전 값 묶음)을 실었으면 `factSectionOld` 로 표시한다 — 사실 주입이 틀린 값을 실어 답을 틀리게 만든 경우를 가르는
자리다. 대명사 두 턴 프로브의 질문 턴은 맥락 턴 응답이 원문 창에 들어 있으므로, 그 응답에 정답이 있으면 "원문 창(맥락 턴)" 으로
따로 센다. 판정은 정답 일치 규칙과 같다.

비밀 문항은 판정자 문항이라 정답 묶음이 없어 `places` 가 언제나 "어디에도 없음" 이다 — 비밀 내용(비밀 묶음)이 실린 자리를
`leakPlaces` 로, 작품 글에 비밀 묶음이 있는지를 `staticTextLeakHit` 로 따로 낸다. 질문 턴에는 결정론 공변량(`secret_covariates`)도 낸다: 섹션(원문 창·요약·사실·회상)마다 비밀
표기가 있나, 비밀 주인 이름이 있나, 둘이 같은 줄·문장에 함께 있나. 비밀 묶음은 하나뿐이라 흔한 낱말 하나로도 표기가 참이 되므로
(다른 인물의 같은 낱말), 함께 있음이 그 오탐을 거른다."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from api.db.models.prompt import PromptSection
from memory_eval.metrics import answer_matches

# 공변량을 내는 섹션 — 이 순서로 낸다.
COVARIATE_SECTIONS = ("원문 창", "요약", "사실", "회상")


def _header_start(prompt: str, header: str) -> int:
    match = re.search(rf"^{re.escape(header)}[ \t]*$", prompt, re.M)
    return -1 if match is None else match.start()


def recall_section(prompt: str, header: str) -> str:
    """그 글자만으로 된 머리글 줄부터 다음 빈 줄 앞까지. 문장 속에서 머리글 이름을 부르는 자리는 섹션이 아니다."""
    start = _header_start(prompt, header)
    if start == -1:
        return ""
    end = prompt.find("\n\n", start)
    return prompt[start:] if end == -1 else prompt[start:end]


@dataclass(frozen=True)
class WindowLayout:
    """원문 창의 경계 — 생성 세트에서 읽은 대화 기록 머리글, 그 뒤에 올 수 있는 섹션 머리글, 마지막 프레임 본문과 라벨."""

    header: str
    stop_headers: tuple[str, ...]
    frame_body: str
    user_label: str
    assistant_label: str

    def frame(self, user_message: str) -> str:
        return self.frame_body.format(
            user_label=self.user_label, user_message=user_message, assistant_label=self.assistant_label
        )


def _first_line(body: str) -> str:
    return body.split("\n", 1)[0]


def window_layout(
    sections: Sequence[PromptSection], *, scope: str, user_label: str, assistant_label: str
) -> WindowLayout:
    """서버는 생성 섹션을 순서대로 빈 줄로 잇고 값이 빈 조건부 섹션은 뺀다. 그래서 대화 기록 뒤에 올 수 있는 섹션은 그 턴에
    무엇이 실렸든 이 세트에서 대화 기록보다 뒤 순서인 섹션 전부다 — 그 머리글을 모두 멈춤 목록에 넣는다. 머리글 없이
    시작하는 마지막 프레임(사용자 질문)은 렌더한 본문 자체로 경계를 찾는다. 그 밖의 머리글 없는 섹션이 뒤에 있으면 경계를
    정할 수 없으니 거부한다."""
    generation = sorted(
        (s for s in sections if s.channel == "generation" and s.scope in ("both", scope)), key=lambda s: s.order
    )
    history = [s for s in generation if s.slot == "history"]
    heads = {_first_line(s.body) for s in history}
    if len(heads) != 1:
        raise SystemExit(f"생성 세트의 대화 기록 머리글이 하나가 아니다({len(heads)}개)")
    header = heads.pop()
    if "{" in header or not header.strip():
        raise SystemExit("생성 세트의 대화 기록 섹션 첫 줄이 머리글이 아니다")
    after = [s for s in generation if s.order > max(h.order for h in history)]
    stops: list[str] = []
    frames: set[str] = set()
    for section in after:
        first = _first_line(section.body)
        if section.slot == "final_frame":
            frames.add(section.body)
        elif "{" in first or not first.strip():
            raise SystemExit(f"대화 기록 뒤 섹션 {section.slot} 에 머리글이 없어 원문 창의 끝을 정할 수 없다")
        elif first not in stops:
            stops.append(first)
    if len(frames) != 1:
        raise SystemExit(f"대화 기록 뒤 마지막 프레임이 하나가 아니다({len(frames)}개)")
    return WindowLayout(header, tuple(stops), frames.pop(), user_label, assistant_label)


def window_section(prompt: str, layout: WindowLayout, *, user_message: str) -> str:
    """원문 창 — 대화 기록 머리글 줄부터, 뒤따를 수 있는 섹션 머리글 줄과 마지막 프레임 가운데 가장 앞의 것 앞까지. 응답에
    빈 줄이 있을 수 있어 빈 줄로는 자르지 않는다. 머리글이나 프레임을 못 찾으면 세트와 프롬프트가 어긋난 것이라, 빈 원문 창이나
    끝까지 늘어난 원문 창으로 거짓 공변량을 내지 않고 거부한다."""
    start = _header_start(prompt, layout.header)
    if start == -1:
        raise SystemExit(f"프롬프트에서 대화 기록 머리글 {layout.header!r} 를 찾지 못했다 — 세트와 프롬프트가 어긋난다")
    ends = [
        m.start()
        for stop in layout.stop_headers
        for m in re.finditer(rf"^{re.escape(stop)}[ \t]*$", prompt, re.M)
        if m.start() > start
    ]
    frame_at = prompt.rfind(layout.frame(user_message))
    if frame_at <= start:
        raise SystemExit("프롬프트에서 대화 기록 뒤 질문 프레임을 찾지 못했다 — 세트와 프롬프트가 어긋난다")
    return prompt[start : min([*ends, frame_at])]


def owner_names(owner: str) -> list[str]:
    """비밀 주인을 부르는 이름: 전체 이름과, 세 글자 한국어 이름이면 성을 뺀 이름(대화는 대개 성 없이 부른다)."""
    return [owner, owner[1:]] if len(owner) == 3 else [owner]


def _units(text: str) -> list[str]:
    """줄과 문장으로 쪼갠 단위 — 비밀 표기와 주인 이름이 함께 있는지 볼 때 쓴다."""
    return [s for line in text.split("\n") for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]


def secret_covariates(
    prompt: str,
    *,
    summary: str,
    recall_header: str,
    fact_header: str | None,
    layout: WindowLayout,
    user_message: str,
    leak_keys: Sequence[Sequence[str]],
    owner: str,
) -> dict[str, dict[str, bool]]:
    """질문 턴 프롬프트의 섹션마다 비밀 표기(`content`)·주인 이름(`owner`)·둘이 한 단위에 함께(`together`). 요약은 그 턴의
    기억 조회 전문이 프롬프트에 그대로 있을 때만 요약 칸이다."""
    texts = {
        "원문 창": window_section(prompt, layout, user_message=user_message),
        "요약": summary if summary.strip() and summary in prompt else "",
        "사실": recall_section(prompt, fact_header) if fact_header else "",
        "회상": recall_section(prompt, recall_header),
    }
    names = owner_names(owner) if owner else []

    def flags(text: str) -> dict[str, bool]:
        return {
            "content": bool(text) and answer_matches(text, leak_keys),
            "owner": any(n in text for n in names),
            "together": any(answer_matches(u, leak_keys) and any(n in u for n in names) for u in _units(text)),
        }

    return {name: flags(texts[name]) for name in COVARIATE_SECTIONS}


def attribute(
    answer_keys: Sequence[Sequence[str]],
    prompt: str,
    *,
    note: str,
    summary: str,
    recall_header: str,
    static_texts: Sequence[str],
    context_response: str | None = None,
    fact_header: str | None = None,
    old_keys: Sequence[Sequence[str]] = (),
    leak_keys: Sequence[Sequence[str]] = (),
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    rest = prompt
    for label, piece in (("노트", note), ("요약", summary)):
        if piece.strip():
            if piece not in rest:
                result["unattributable"] = f"덤프에서 {label} 원문을 찾지 못함"
                return result
            rest = rest.replace(piece, "", 1)
    recall = recall_section(rest, recall_header)
    if recall:
        rest = rest.replace(recall, "", 1)
    facts = recall_section(rest, fact_header) if fact_header else ""
    if facts:
        rest = rest.replace(facts, "", 1)
    context_place = ""
    if context_response and context_response in rest:
        rest = rest.replace(context_response, "", 1)
        context_place = context_response
    pieces = (
        ("노트", note),
        ("요약", summary),
        ("회상", recall),
        ("사실", facts),
        ("원문 창(맥락 턴)", context_place),
        ("원문 윈도", rest),
    )

    def places(keys: Sequence[Sequence[str]]) -> list[str]:
        return [name for name, text in pieces if text and answer_matches(text, keys)] or ["어디에도 없음"]

    result["places"] = places(answer_keys)
    if leak_keys:
        result["leakPlaces"] = places(leak_keys)
    if facts:
        result["factSectionOld"] = bool(old_keys) and answer_matches(facts, old_keys)
    # 작품 글에도 정답이 있으면 원문 윈도 자리에 작품 글이 섞였다는 표시 — 판독 때 본다.
    result["staticTextHit"] = any(bool(t) and answer_matches(t, answer_keys) for t in static_texts)
    # 비밀 문항은 정답 묶음이 없어 위 표시가 늘 거짓이다 — 비밀 묶음이 작품 글에 있는지 따로 표시한다.
    if leak_keys:
        result["staticTextLeakHit"] = any(bool(t) and answer_matches(t, leak_keys) for t in static_texts)
    return result
