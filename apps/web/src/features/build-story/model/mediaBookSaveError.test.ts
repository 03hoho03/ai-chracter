import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  ENDING_RULE_STAT_NOT_FOUND_MESSAGE,
  isEndingRuleStatNotFoundError,
  MEDIA_BOOK_POSITION_TAKEN_MESSAGE,
  STORY_SAVE_LIMIT_MESSAGE,
  storyAutosaveErrorMessage,
} from "./mediaBookSaveError";

describe("storyAutosaveErrorMessage", () => {
  it("explains the media book position conflict so the user reloads instead of waiting", () => {
    const error = new ApiErrorObject({
      status: 409,
      message: "conflict",
      detail: { code: "MEDIA_BOOK_CELL_POSITION_TAKEN" },
    });

    expect(storyAutosaveErrorMessage(error)).toBe(MEDIA_BOOK_POSITION_TAKEN_MESSAGE);
  });

  it("falls back to the default message for other failures", () => {
    expect(storyAutosaveErrorMessage(new ApiErrorObject({ status: 409, message: "x", detail: { code: "OTHER" } }))).toBeUndefined();
    expect(storyAutosaveErrorMessage(new ApiErrorObject({ status: 500, message: "x", detail: "boom" }))).toBeUndefined();
    expect(storyAutosaveErrorMessage(new ApiErrorObject({ status: 0, message: "Network Error", detail: undefined }))).toBeUndefined();
    expect(storyAutosaveErrorMessage(new Error("network"))).toBeUndefined();
  });

  it("tells the user to shorten something on a 422 instead of asking them to wait", () => {
    // 422 본문은 어느 필드가 넘쳤는지 화면이 가려 읽을 수 없는 모양이라 상태 코드만 본다.
    const error = new ApiErrorObject({ status: 422, message: "Field required", detail: undefined, fields: {} });

    expect(storyAutosaveErrorMessage(error)).toBe(STORY_SAVE_LIMIT_MESSAGE);
    expect(STORY_SAVE_LIMIT_MESSAGE).not.toMatch(/잠시 후/);
  });

  it("names the deleted-stat ending condition instead of blaming length limits", () => {
    const error = new ApiErrorObject({
      status: 422,
      message: "Request failed with status code 422",
      detail: {
        code: "ENDING_RULE_STAT_NOT_FOUND",
        paths: ["startingSetups[0].endings[1].statRules[0].statId"],
      },
    });

    expect(storyAutosaveErrorMessage(error)).toBe(ENDING_RULE_STAT_NOT_FOUND_MESSAGE);
    expect(ENDING_RULE_STAT_NOT_FOUND_MESSAGE).toMatch(/엔딩/);
    // 편집기가 그런 조건의 스탯 칸에 그리는 글자로 가리켜야 작가가 화면에서 찾는다.
    expect(ENDING_RULE_STAT_NOT_FOUND_MESSAGE).toContain("‘지워짐’이 보이는 조건");
    expect(ENDING_RULE_STAT_NOT_FOUND_MESSAGE).not.toMatch(/글자 수|잠시 후/);
  });

  // 서버는 엔딩의 우선순위 스탯이 지워진 스탯을 가리킬 때도 같은 코드로 거절한다 — 조건만 말하면 작가가 조건만 찾다 멈춘다.
  it("also tells how to fix a deleted priority stat, which the server rejects with the same code", () => {
    const error = new ApiErrorObject({
      status: 422,
      message: "Request failed with status code 422",
      detail: { code: "ENDING_RULE_STAT_NOT_FOUND", paths: ["startingSetups[0].endings[2].priorityStatId"] },
    });

    expect(storyAutosaveErrorMessage(error)).toBe(ENDING_RULE_STAT_NOT_FOUND_MESSAGE);
    expect(ENDING_RULE_STAT_NOT_FOUND_MESSAGE).toContain("우선순위 스탯은 다른 스탯이나 ‘없음’으로");
  });
});

describe("isEndingRuleStatNotFoundError", () => {
  // 발행 버튼은 발행 전에 초안을 저장한다. 그 저장이 지워진 스탯 조건으로 거절되면 일반 실패 문구 대신 이 판정으로 갈라
  // 엔딩 탭으로 보낸다. 글자 수 422 나 다른 상태 코드까지 잡으면 엉뚱한 탭으로 보내게 된다.
  it("recognizes only the deleted-stat ending condition rejection", () => {
    const endingRule = new ApiErrorObject({
      status: 422,
      message: "Request failed with status code 422",
      detail: { code: "ENDING_RULE_STAT_NOT_FOUND", paths: [] },
    });
    const lengthLimit = new ApiErrorObject({ status: 422, message: "Field required", detail: undefined, fields: {} });
    const otherStatus = new ApiErrorObject({
      status: 400,
      message: "Request failed with status code 400",
      detail: { code: "ENDING_RULE_STAT_NOT_FOUND" },
    });

    expect(isEndingRuleStatNotFoundError(endingRule)).toBe(true);
    expect(isEndingRuleStatNotFoundError(lengthLimit)).toBe(false);
    expect(isEndingRuleStatNotFoundError(otherStatus)).toBe(false);
    expect(isEndingRuleStatNotFoundError(new Error("network"))).toBe(false);
  });
});
