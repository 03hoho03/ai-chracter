import type { Path } from "react-hook-form";

import { isApiError } from "@/shared/api/client";

import { isMissingStat } from "./missingStatRules";
import {
  countRules,
  SITUATION_NOTE_BLANK_CONTENT_MESSAGE,
  SITUATION_NOTE_EMPTY_CONDITIONS_MESSAGE,
  type RuleListItemValues,
  type StartingSetupValues,
  type StoryBuilderFormValues,
} from "./schema";

// 상황 노트 조건이 같은 시작설정에 없는 스탯을 가리킬 때 서버가 초안 저장에 돌려주는 422 의 `detail.code`. 응답에 실리는 실제
// 식별자다(엔딩 조건과 코드가 따로라 엔딩 탭으로 잘못 보내지 않는다).
const SITUATION_NOTE_STAT_NOT_FOUND_CODE = "SITUATION_NOTE_STAT_NOT_FOUND";

/**
 * 상황 노트 조건이 지워진 스탯을 가리켜 저장이 거절된 경우의 안내. 글자 수 문제가 아니므로 줄이라고 하지 않고 고칠 자리를
 * 짚는다. 이 화면에서 스탯을 지우면 그 조건도 함께 지워지므로, 다른 기기에서 고친 초안처럼 서버만 아는 상태에서만 보인다.
 * 그런 조건 줄은 스탯 칸에 '지워짐'이 보이므로 문구도 그 글자로 자리를 가리킨다.
 */
export const SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE =
  "지워진 스탯을 쓰는 상황 노트 조건이 있어 저장하지 못했어요. 입력한 내용은 그대로 있으니 상황 노트 탭에서 스탯 칸에 ‘지워짐’이 보이는 조건을 지우거나 다른 스탯으로 바꿔주세요.";

/** 조건 줄의 스탯 칸이 지워진 스탯을 가리킬 때 그 칸에 거는 오류 문구. 줄 아래에 고치는 법이 이미 보이므로 짧게 둔다. */
const MISSING_STAT_RULE_MESSAGE = "지워진 스탯이에요";

export function isSituationNoteStatNotFoundError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 422) return false;
  return typeof error.detail === "object" && error.detail.code === SITUATION_NOTE_STAT_NOT_FOUND_CODE;
}

// 서버 경로 `startingSetups[0].situationNotes[1].conditionRules[2].statId`(그룹 안이면 `…conditionRules[2].rules[0].statId`).
const SERVER_RULE_PATH =
  /^startingSetups\[(\d+)\]\.situationNotes\[(\d+)\]\.conditionRules\[(\d+)\](?:\.rules\[(\d+)\])?\.statId$/;

type RuleLocation = { setupIndex: number; noteIndex: number; ruleIndex: number; innerIndex: number | undefined };

function ruleStatIdPath({ setupIndex, noteIndex, ruleIndex, innerIndex }: RuleLocation): Path<StoryBuilderFormValues> {
  const rulePath = `startingSetups.${setupIndex}.situationNotes.${noteIndex}.conditionRules.${ruleIndex}` as const;
  return innerIndex === undefined ? `${rulePath}.statId` : `${rulePath}.rules.${innerIndex}.statId`;
}

/**
 * 저장 거절(422)이 가리킨 조건 줄들의 폼 경로. 이 오류가 아니면 `undefined`, 이 오류인데 읽을 수 있는 경로가 없으면 빈 목록이다
 * — 그때 호출부는 상황 노트 목록 자리로 대신 보낸다. 모양이 다른 경로는 버린다(서버가 보낸 외부 문자열이라 폼 경로로 그대로 쓰지
 * 않는다).
 */
export function situationNoteStatNotFoundPaths(error: unknown): Path<StoryBuilderFormValues>[] | undefined {
  if (!isSituationNoteStatNotFoundError(error) || !isApiError(error) || typeof error.detail !== "object") return undefined;
  const rawPaths: unknown = error.detail.paths;
  if (!Array.isArray(rawPaths)) return [];
  return rawPaths.flatMap((raw) => {
    const match = typeof raw === "string" ? SERVER_RULE_PATH.exec(raw) : null;
    if (!match) return [];
    const [, setup, note, rule, inner] = match;
    return [
      ruleStatIdPath({
        setupIndex: Number(setup),
        noteIndex: Number(note),
        ruleIndex: Number(rule),
        innerIndex: inner === undefined ? undefined : Number(inner),
      }),
    ];
  });
}

export type SituationNoteErrorLocation = { path: Path<StoryBuilderFormValues>; message: string };

/**
 * 발행 400 의 상황 노트 키(`missingFields`)가 가리키는 첫 노트 칸을 폼에서 찾는다. 서버는 어느 노트인지 알려 주지 않지만 같은
 * 조건(조건 0개 · 상황 공백 · 지워진 스탯 조건)을 폼 값에서 다시 따지면 그 칸을 짚을 수 있다. 상황 노트 키가 아니거나 폼에서
 * 찾지 못하면(서버만 아는 상태) `undefined` — 호출부는 목록 자리로 대신 보낸다.
 */
export function locateSituationNotePublishError(
  field: string,
  startingSetups: readonly StartingSetupValues[],
): SituationNoteErrorLocation | undefined {
  for (const [setupIndex, setup] of startingSetups.entries()) {
    for (const [noteIndex, note] of setup.situationNotes.entries()) {
      const notePath = `startingSetups.${setupIndex}.situationNotes.${noteIndex}` as const;
      if (field === "situationNotes.emptyConditionRules" && countRules(note.conditionRules) === 0) {
        return { path: `${notePath}.conditionRules`, message: SITUATION_NOTE_EMPTY_CONDITIONS_MESSAGE };
      }
      if (field === "situationNotes.infoText" && note.content.trim().length === 0) {
        return { path: `${notePath}.content`, message: SITUATION_NOTE_BLANK_CONTENT_MESSAGE };
      }
      if (field === "situationNotes.conditionRules") {
        const rule = firstMissingStatRule(note.conditionRules, setup.stats);
        if (rule) return { path: ruleStatIdPath({ setupIndex, noteIndex, ...rule }), message: MISSING_STAT_RULE_MESSAGE };
      }
    }
  }
  return undefined;
}

function firstMissingStatRule(
  rules: readonly RuleListItemValues[],
  stats: readonly { id: string }[],
): Pick<RuleLocation, "ruleIndex" | "innerIndex"> | undefined {
  for (const [ruleIndex, item] of rules.entries()) {
    if (item.kind === "rule") {
      if (isMissingStat(item.statId, stats)) return { ruleIndex, innerIndex: undefined };
      continue;
    }
    const innerIndex = item.rules.findIndex((rule) => isMissingStat(rule.statId, stats));
    if (innerIndex !== -1) return { ruleIndex, innerIndex };
  }
  return undefined;
}
