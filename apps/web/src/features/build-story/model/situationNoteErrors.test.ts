import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { storyAutosaveErrorMessage } from "./mediaBookSaveError";
import type { StartingSetupValues, StatDefValues } from "./schema";
import {
  isSituationNoteStatNotFoundError,
  locateSituationNotePublishError,
  SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE,
  situationNoteStatNotFoundPaths,
} from "./situationNoteErrors";

function saveRejection(code: string, paths?: unknown): ApiErrorObject {
  return new ApiErrorObject({
    status: 422,
    message: "Request failed with status code 422",
    detail: paths === undefined ? { code } : { code, paths },
  });
}

describe("저장 거절 — 지워진 스탯을 쓰는 상황 노트 조건", () => {
  it("자동저장 실패 문구가 글자 수가 아니라 상황 노트 탭의 '지워진 스탯' 조건을 가리킨다", () => {
    const message = storyAutosaveErrorMessage(saveRejection("SITUATION_NOTE_STAT_NOT_FOUND"));

    expect(message).toBe(SITUATION_NOTE_STAT_NOT_FOUND_MESSAGE);
    expect(message).toContain("상황 노트 탭");
    // 편집기가 그런 조건의 스탯 칸에 그리는 이름과 같은 말이어야 작가가 화면에서 찾는다.
    expect(message).toContain("‘지워진 스탯’");
    expect(message).not.toMatch(/글자 수|엔딩/);
  });

  // 엔딩 조건과 코드가 따로라 엔딩 거절을 상황 노트로 잡으면 엉뚱한 탭으로 보낸다.
  it("엔딩 조건 거절이나 다른 422 는 상황 노트 거절로 보지 않는다", () => {
    expect(isSituationNoteStatNotFoundError(saveRejection("ENDING_RULE_STAT_NOT_FOUND"))).toBe(false);
    expect(isSituationNoteStatNotFoundError(new ApiErrorObject({ status: 422, message: "x", detail: undefined }))).toBe(
      false,
    );
    expect(isSituationNoteStatNotFoundError(new Error("network"))).toBe(false);
  });

  it("서버 경로를 조건 줄의 스탯 칸 폼 경로로 옮긴다(그룹 안 조건 포함)", () => {
    const error = saveRejection("SITUATION_NOTE_STAT_NOT_FOUND", [
      "startingSetups[1].situationNotes[0].conditionRules[2].statId",
      "startingSetups[0].situationNotes[3].conditionRules[1].rules[4].statId",
    ]);

    expect(situationNoteStatNotFoundPaths(error)).toEqual([
      "startingSetups.1.situationNotes.0.conditionRules.2.statId",
      "startingSetups.0.situationNotes.3.conditionRules.1.rules.4.statId",
    ]);
  });

  // 서버가 준 외부 문자열이라 모양이 다르면 폼 경로로 쓰지 않는다 — 호출부는 빈 목록이면 상황 노트 목록 자리로 보낸다.
  it("모양이 다른 경로는 버리고, 경로가 없으면 빈 목록이다", () => {
    expect(
      situationNoteStatNotFoundPaths(
        saveRejection("SITUATION_NOTE_STAT_NOT_FOUND", ["startingSetups[0].endings[0].statRules[0].statId", 3]),
      ),
    ).toEqual([]);
    expect(situationNoteStatNotFoundPaths(saveRejection("SITUATION_NOTE_STAT_NOT_FOUND"))).toEqual([]);
  });

  it("이 거절이 아니면 undefined 다", () => {
    expect(situationNoteStatNotFoundPaths(saveRejection("ENDING_RULE_STAT_NOT_FOUND", []))).toBeUndefined();
  });
});

const STAT: StatDefValues = {
  id: "kept",
  name: "상영회까지",
  icon: "Heart",
  color: "c",
  min: 0,
  max: 42,
  initial: 42,
  description: "d",
  perTurnDelta: null,
  changeDirection: "both",
  maxChangePerTurn: null,
};

function setup(situationNotes: StartingSetupValues["situationNotes"]): StartingSetupValues {
  return { id: "s", name: "", prologue: "", suggestedReplies: [], stats: [STAT], endings: [], situationNotes };
}

const OK_RULE = { kind: "rule", id: "ok", statId: "kept", operator: "<=", value: 0, nextOp: null } as const;

describe("locateSituationNotePublishError", () => {
  const setups = [
    setup([{ id: "a", name: "", content: "사실", conditionRules: [OK_RULE] }]),
    setup([
      { id: "b", name: "", content: "사실", conditionRules: [OK_RULE] },
      { id: "c", name: "", content: "  ", conditionRules: [] },
      {
        id: "d",
        name: "",
        content: "사실",
        conditionRules: [OK_RULE, { kind: "group", id: "g", nextOp: null, rules: [OK_RULE, { ...OK_RULE, id: "x", statId: "gone" }] }],
      },
    ]),
  ];

  // 발행 400 은 어느 노트인지 알려 주지 않는다. 폼에서 같은 조건을 다시 따져 그 노트의 칸을 짚어야 셸이 그 노트를 열고 포커스한다.
  it("조건 없는 노트의 조건 칸을 짚는다", () => {
    expect(locateSituationNotePublishError("situationNotes.emptyConditionRules", setups)?.path).toBe(
      "startingSetups.1.situationNotes.1.conditionRules",
    );
  });

  it("상황이 공백뿐인 노트의 상황 칸을 짚는다", () => {
    expect(locateSituationNotePublishError("situationNotes.infoText", setups)?.path).toBe(
      "startingSetups.1.situationNotes.1.content",
    );
  });

  it("지워진 스탯을 쓰는 조건 줄의 스탯 칸을 짚는다(그룹 안 조건 포함)", () => {
    expect(locateSituationNotePublishError("situationNotes.conditionRules", setups)?.path).toBe(
      "startingSetups.1.situationNotes.2.conditionRules.1.rules.1.statId",
    );
  });

  // 폼에서 못 찾는 상태(다른 기기에서 고친 초안 등)와 상황 노트가 아닌 키는 호출부의 기본 경로가 맡는다.
  it("폼에서 찾지 못하거나 상황 노트 키가 아니면 undefined 다", () => {
    const clean = [setup([{ id: "a", name: "", content: "사실", conditionRules: [OK_RULE] }])];

    expect(locateSituationNotePublishError("situationNotes.emptyConditionRules", clean)).toBeUndefined();
    expect(locateSituationNotePublishError("situationNotes.conditionRules", clean)).toBeUndefined();
    expect(locateSituationNotePublishError("endings.statRules", setups)).toBeUndefined();
  });
});
