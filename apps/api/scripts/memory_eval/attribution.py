"""출처 귀속 — 정답이 생성 프롬프트(서버 덤프)의 어느 자리에 실렸나: 기억 노트 · 요약 · 회상 · 원문 윈도 · 어디에도 없음.

앞선 장기 측정의 귀속 규칙을 따른다: 노트·요약은 그 턴의 기억 조회 전문에서 문자열 그대로 찾아 덤프에서 떼어 내고, 나머지를
원문 윈도로 본다. 문자열을 덤프에서 그대로 찾지 못하면 귀속하지 않는다(다른 판의 요약을 보고 있다는 뜻). 회상 섹션과 사실
섹션도 머리글부터 다음 빈 줄까지를 떼어 내 따로 센다. 사실 섹션이 옛 값(정정 전 값 묶음)을 실었으면 `factSectionOld` 로 표시한다 —
사실 주입이 틀린 값을 실어 답을 틀리게 만든 경우를 가르는 자리다. 대명사 두 턴 프로브의 질문 턴은 맥락 턴 응답이 원문 창에 들어 있으므로,
그 응답에 정답이 있으면 "원문 창(맥락 턴)" 으로 따로 센다. 판정은 정답 일치 규칙과 같다."""

from collections.abc import Sequence
from typing import Any

from memory_eval.metrics import answer_matches


def recall_section(prompt: str, header: str) -> str:
    start = prompt.find(header)
    if start == -1:
        return ""
    end = prompt.find("\n\n", start)
    return prompt[start:] if end == -1 else prompt[start:end]


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

    def hit(text: str) -> bool:
        return bool(text) and answer_matches(text, answer_keys)

    places = [
        name
        for name, text in (
            ("노트", note),
            ("요약", summary),
            ("회상", recall),
            ("사실", facts),
            ("원문 창(맥락 턴)", context_place),
            ("원문 윈도", rest),
        )
        if hit(text)
    ]
    result["places"] = places or ["어디에도 없음"]
    if facts:
        result["factSectionOld"] = bool(old_keys) and answer_matches(facts, old_keys)
    # 작품 글에도 정답이 있으면 원문 윈도 자리에 작품 글이 섞였다는 표시 — 판독 때 본다.
    result["staticTextHit"] = any(hit(t) for t in static_texts)
    return result
