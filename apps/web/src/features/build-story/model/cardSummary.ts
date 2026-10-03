import { firstLine } from "@/shared/lib/text/firstLine";

import { isMissingStat } from "./missingStatRules";
import {
  countRules,
  type EndingValues,
  type KeywordNoteValues,
  type RuleListItemValues,
  type SituationNoteValues,
  type StartingSetupValues,
  type StatDefValues,
} from "./schema";

// 접힌 카드 머리 줄의 제목·요약 글. 빌더 카드와 작성 가이드의 카드 모양 예시가 같은 함수로 만들어 두 화면의 요약이
// 어긋나지 않게 한다. 요약 조각은 ` · ` 로 잇고 비어 있는 재료는 뺀다.

/** 첫 시작설정이 기본 선택이라 그 사실과 프롤로그 첫 줄로 가른다. */
export function startingSetupSummary(setup: Pick<StartingSetupValues, "prologue">, index: number): string {
  return [index === 0 ? "기본" : undefined, firstLine(setup.prologue) || undefined]
    .filter((part) => part !== undefined)
    .join(" · ");
}

/**
 * 판정이 시작되는 턴과 조건 수. 그룹 안의 조건도 하나씩 센다 — 작가가 보는 "조건" 수다.
 *
 * 규칙은 종류와 그룹 안 개수만 본다. 작성 가이드는 폼 값(규칙 id·스탯 id)이 아니라 원고의 시드 모양 규칙을 넘기므로
 * 폼 타입 전체를 요구하지 않는다.
 */
export function endingSummary(ending: {
  turnGate: EndingValues["turnGate"];
  statRules: readonly ({ kind: "rule" } | { kind: "group"; rules: readonly unknown[] })[];
}): string {
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

/** 이름이 비면 상황 글의 첫 줄로 목록에서 노트를 가른다(키워드 노트가 첫 트리거 키워드를 쓰는 것과 같은 판단). */
export function situationNoteTitle(note: Pick<SituationNoteValues, "name" | "content">): string {
  return note.name.trim() || firstLine(note.content);
}

/**
 * 상황 노트 카드 머리 줄의 조건 요약. 노트를 가르는 재료가 조건이라 첫 조건을 글로 보이고 나머지는 개수로 접는다
 * (`상영회까지 <= 0 외 1개`). 첫 항목이 그룹이면 한 줄로 옮길 수 없어 전체 개수만(`조건 3개`), 조건이 없으면 `조건 없음`.
 * 개수는 편집기의 상한과 같은 셈이다(그룹 자체는 세지 않는다). 스탯 이름과 연산자는 조건 줄의 셀렉트가 그리는 글자와 같게
 * 쓰고, 지워진 스탯을 가리키면 `지워진 스탯` 이다(줄의 스탯 칸은 좁아 `지워짐` 만 보이지만, 머리 줄은 자리가 있어 온전히 쓴다).
 */
export function situationNoteConditionSummary(
  rules: readonly RuleListItemValues[],
  stats: readonly Pick<StatDefValues, "id" | "name">[],
): string {
  const count = countRules(rules);
  const [first] = rules;
  if (count === 0 || first === undefined) return "조건 없음";
  if (first.kind === "group") return `조건 ${count}개`;

  const statName = isMissingStat(first.statId, stats)
    ? "지워진 스탯"
    : stats.find((stat) => stat.id === first.statId)?.name || "이름없음";
  const text = `${statName} ${first.operator} ${first.value}`;
  return count > 1 ? `${text} 외 ${count - 1}개` : text;
}
