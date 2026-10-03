import { firstLine } from "@/shared/lib/text/firstLine";

import type { EndingValues, KeywordNoteValues, StartingSetupValues } from "./schema";

// 접힌 카드 머리 줄의 제목·요약 글. 빌더 카드와 작성 가이드의 카드 모양 예시가 같은 함수로 만들어 두 화면의 요약이
// 어긋나지 않게 한다. 요약 조각은 ` · ` 로 잇고 비어 있는 재료는 뺀다.

/** 첫 시작설정이 기본 선택이라 그 사실과 프롤로그 첫 줄로 가른다. */
export function startingSetupSummary(setup: Pick<StartingSetupValues, "prologue">, index: number): string {
  return [index === 0 ? "기본" : undefined, firstLine(setup.prologue) || undefined]
    .filter((part) => part !== undefined)
    .join(" · ");
}

/** 판정이 시작되는 턴과 조건 수. 그룹 안의 조건도 하나씩 센다 — 작가가 보는 "조건" 수다. */
export function endingSummary(ending: Pick<EndingValues, "turnGate" | "statRules">): string {
  const ruleCount = ending.statRules.reduce((sum, item) => sum + (item.kind === "group" ? item.rules.length : 1), 0);
  return [Number.isFinite(ending.turnGate) ? `${ending.turnGate}턴 이후` : undefined, `규칙 ${ruleCount}개`]
    .filter((part) => part !== undefined)
    .join(" · ");
}

/** 이름이 없으면 첫 트리거 키워드로 부른다. 둘 다 없으면 없음(카드가 자리표시 제목을 그린다). */
export function keywordNoteTitle(note: Pick<KeywordNoteValues, "name" | "triggerKeywords">): string | undefined {
  return note.name.trim() || note.triggerKeywords[0];
}

export type KeywordNoteSummary = {
  text: string;
  /** 상시 노트 — 요약을 강조해 그린다. */
  isAlwaysOn: boolean;
};

/** 상시 여부나 유지 턴, 트리거 개수. 상시 노트는 트리거 키워드와 유지 턴을 쓰지 않아 `상시` 만 보인다. */
export function keywordNoteSummary(
  note: Pick<KeywordNoteValues, "alwaysOn" | "stickyTurns" | "triggerKeywords">,
): KeywordNoteSummary {
  if (note.alwaysOn) return { text: "상시", isAlwaysOn: true };
  const sticky = note.stickyTurns > 0 ? `유지 ${note.stickyTurns}턴 · ` : "";
  return { text: `${sticky}트리거 ${note.triggerKeywords.length}개`, isAlwaysOn: false };
}
