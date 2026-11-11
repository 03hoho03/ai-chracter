import type { LabMode } from "@/shared/api/labMode";
import { assertNever } from "@/shared/lib/assertNever";

import type { RawField, RawView } from "./rawSource";

/**
 * 원문 칸에 원문이 없을 때 그 자리에 둘 문장 — 왜 없는지. 덤프가 없는 묶음·원문을 뺀 기록·고르지 않은 시도·원래 없는 칸이 같은
 * 모양이 되지 않게 한다. 원문을 뺀 기록만 모드에 따라 무엇을 하면 원문까지 보는지가 다르다 — 정적 파일은 다시 내보내고, 호스팅
 * 화면은 올린 사람이 다시 올린다(이 화면에는 원문을 고르는 조작이 없다).
 */
export function rawAbsentText(view: Exclude<RawView, { kind: "text" }>, mode: LabMode): string {
  switch (view.kind) {
    case "noDumpFile":
      return view.text;
    case "notSelectedAttempt":
      return view.earlierCount > 0
        ? `덤프 없음 — 생성 덤프는 DB 응답으로 고른 시도에만 붙는다. 이 턴의 앞선 생성 덤프 ${view.earlierCount}개는 어느 시도의 것인지 가르지 않아 출처에서 따로 연다.`
        : "덤프 없음 — 생성 덤프는 DB 응답으로 고른 시도에만 붙는다.";
    case "noDumpForAttempt":
      return "덤프 없음 — 이 출처에 붙은 덤프 줄이 없다.";
    case "excluded":
      return mode === "hosted" ? hostedExcludedText(view.field) : staticExcludedText(view.field);
    case "emptyPrompt":
      return "이 덤프 줄의 프롬프트 칸이 비어 있다 — 칸은 있지만 글이 아닌 값이 적혀 있다.";
    case "noField":
      return "이 덤프 줄에는 지시문 칸이 없다 — 지시문을 따로 보내지 않은 호출이다.";
    default:
      return assertNever(view);
  }
}

function staticExcludedText(field: RawField): string {
  return field === "prompt"
    ? "원문 제외 — 이 파일은 프롬프트·지시문 원문을 빼고 내보냈다. 원문까지 보려면 원문 포함(--raw)으로 다시 내보낸다."
    : "원문 제외 — 이 파일은 원문 없이 내보내, 이 호출이 지시문을 따로 보냈는지도 이 파일로는 알 수 없다. 원문까지 보려면 원문 포함(--raw)으로 다시 내보낸다.";
}

function hostedExcludedText(field: RawField): string {
  return field === "prompt"
    ? "원문 제외 — 이 판은 프롬프트·지시문 원문을 빼고 올렸다. 원문까지 보려면 올린 사람이 원문 포함(--raw)으로 다시 올린다."
    : "원문 제외 — 이 판은 원문 없이 올려, 이 호출이 지시문을 따로 보냈는지도 이 판으로는 알 수 없다. 원문까지 보려면 올린 사람이 원문 포함(--raw)으로 다시 올린다.";
}
