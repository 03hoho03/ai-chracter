import {
  endingSummary,
  keywordNoteSummary,
  keywordNoteTitle,
  startingSetupSummary,
  STORY_FIELD_LABELS,
  type StatDefValues,
  type StoryFieldKey,
} from "@/features/build-story";
import { firstLine } from "@/shared/lib/text/firstLine";

import { isRecord } from "./mockupValue";

export type MockupCardHeader = {
  /** 카드 제목. 비면 빌더처럼 흐린 자리표시 제목(`placeholderTitle`)을 그린다. */
  title: string;
  placeholderTitle: string;
  summary: string;
  /** 스탯 카드만 — 요약 자리를 글 대신 빌더와 같은 스탯 요약(아이콘·색 점·범위·초기값)으로 그린다. */
  stat: Pick<StatDefValues, "icon" | "color" | "min" | "max" | "initial" | "unit" | "perTurnDelta"> | null;
};

/**
 * 원고의 반복 카드 목록 값(카드 하나 = 객체)에서 접힌 머리 줄의 제목·요약을 만든다. 요약 글은 빌더 카드와 같은 함수로
 * 만든다 — 원고에 요약 글을 따로 쓰면 빌더 요약 규칙이 바뀌었을 때 가이드 그림만 옛 모양으로 남는다.
 *
 * 원고 카드에는 빌더 폼의 모든 값이 있지 않다. 없는 값은 빌더의 새 카드 기본값(상시 적용 꺼짐·유지 턴 0·단위 없음·턴당
 * 변화 없음)으로 본다.
 */
export function mockupCardHeader(listKey: StoryFieldKey, card: Record<string, unknown>, index: number): MockupCardHeader {
  const placeholderTitle = `${STORY_FIELD_LABELS[listKey].label} ${index + 1}`;
  const name = readString(card, "name");
  const base = { title: name, placeholderTitle, summary: "", stat: null };

  switch (listKey) {
    case "storySetting.developmentExamples":
      // 전개 예시는 이름 칸이 없어 빌더도 순번 자리표시를 제목으로, 사용자 메시지 첫 줄을 요약으로 쓴다.
      return { ...base, title: "", summary: firstLine(readString(card, "userLine")) };
    case "startingSetups":
      return { ...base, summary: startingSetupSummary({ prologue: readString(card, "prologue") }, index) };
    case "startingSetups.*.stats":
      return {
        ...base,
        stat: {
          icon: readString(card, "icon"),
          color: readString(card, "color"),
          min: readNumber(card, "min"),
          max: readNumber(card, "max"),
          initial: readNumber(card, "initial"),
          unit: undefined,
          perTurnDelta: null,
        },
      };
    case "keywordNotes": {
      const triggerKeywords = readStrings(card, "triggerKeywords");
      const note = { name, triggerKeywords, alwaysOn: card.alwaysOn === true, stickyTurns: readNumber(card, "stickyTurns", 0) };
      return { ...base, title: keywordNoteTitle(note) ?? "", summary: keywordNoteSummary(note).text };
    }
    case "startingSetups.*.endings":
      return {
        ...base,
        summary: endingSummary({ turnGate: readNumber(card, "turnGate"), statRules: readRules(card.statRules) }),
      };
    default:
      return base;
  }
}

function readString(card: Record<string, unknown>, key: string): string {
  const value = card[key];
  return typeof value === "string" ? value : "";
}

/** 숫자가 아니면 NaN — 빌더 요약 함수가 숫자가 아닌 값의 조각을 빼는 규칙을 그대로 받는다. */
function readNumber(card: Record<string, unknown>, key: string, fallback = Number.NaN): number {
  const value = card[key];
  return typeof value === "number" ? value : fallback;
}

function readStrings(card: Record<string, unknown>, key: string): string[] {
  const value = card[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function readRules(value: unknown): ({ kind: "rule" } | { kind: "group"; rules: unknown[] })[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((rule) =>
    rule.kind === "group" && Array.isArray(rule.rules) ? { kind: "group", rules: rule.rules } : { kind: "rule" },
  );
}
