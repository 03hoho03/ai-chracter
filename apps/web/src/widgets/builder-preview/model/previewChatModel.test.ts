import { describe, expect, it } from "vitest";

import {
  isPreviewModelSelectable,
  previewDisplayModel,
  previewModelNeedsConfirm,
  previewStartQuery,
  previewTurnCost,
} from "./previewChatModel";

describe("previewDisplayModel", () => {
  it("상위 모델 기능이 켜져 있으면 고른 상위 모델이 화면의 모델이다", () => {
    expect(previewDisplayModel(["chat_premium_models"], "opus")).toBe("opus");
  });

  // 서버는 스위치가 꺼지면 세션에 저장된 상위 모델 대신 기본 모델로 답한다. 화면도 같은 식이어야 칩·잔량·단가가 실제와 맞다.
  it("기능이 꺼져 있으면 상위 모델을 골라 두었어도 기본 모델이다", () => {
    expect(previewDisplayModel([], "opus")).toBe("gemini");
    expect(previewDisplayModel(undefined, "opus")).toBe("gemini");
  });

  it("기본 모델을 골랐으면 기능과 무관하게 기본 모델이다", () => {
    expect(previewDisplayModel(["chat_premium_models"], "gemini")).toBe("gemini");
    expect(previewDisplayModel([], "gemini")).toBe("gemini");
  });
});

describe("isPreviewModelSelectable", () => {
  it("상위 모델 기능이 있을 때만 모델을 고를 수 있다", () => {
    expect(isPreviewModelSelectable(["chat_premium_models"])).toBe(true);
    expect(isPreviewModelSelectable([])).toBe(false);
    expect(isPreviewModelSelectable(undefined)).toBe(false);
  });
});

describe("previewModelNeedsConfirm", () => {
  it("세션이 없을 때 상위 모델로 가면 클로버 사용 동의를 묻는다", () => {
    expect(previewModelNeedsConfirm("opus", false)).toBe(true);
  });

  it("세션이 없을 때 기본 모델로 가면 묻지 않는다 — 대화방과 같다", () => {
    expect(previewModelNeedsConfirm("gemini", false)).toBe(false);
  });

  it("세션이 있으면 상위 모델로 가도 묻는다", () => {
    expect(previewModelNeedsConfirm("opus", true)).toBe(true);
  });

  // 돈 때문이 아니라 진행 중인 미리보기 대화를 잃기 때문에 묻는다.
  it("세션이 있으면 기본 모델로 돌아가는 것도 묻는다", () => {
    expect(previewModelNeedsConfirm("gemini", true)).toBe(true);
  });
});

describe("previewStartQuery", () => {
  // 기본 모델 요청은 모델 선택이 생기기 전과 같아야 모델 쿼리를 모르는 서버와 겹치는 동안에도 경로가 바뀌지 않는다.
  it("기본 모델이면 쿼리를 싣지 않는다", () => {
    expect(previewStartQuery("gemini")).toBeUndefined();
  });

  it("상위 모델이면 그 모델을 쿼리로 싣는다", () => {
    expect(previewStartQuery("opus")).toEqual({ model: "opus" });
  });
});

describe("previewTurnCost", () => {
  const models = [
    { id: "gemini" as const, turnCost: 10 },
    { id: "opus" as const, turnCost: 120 },
  ];

  it("화면의 모델 한 턴 가격을 목록에서 읽는다", () => {
    expect(previewTurnCost(models, "opus")).toBe(120);
    expect(previewTurnCost(models, "gemini")).toBe(10);
  });

  it("목록이 없거나 그 모델이 빠져 있으면 undefined 다", () => {
    expect(previewTurnCost(undefined, "opus")).toBeUndefined();
    expect(previewTurnCost([{ id: "gemini" as const, turnCost: 10 }], "opus")).toBeUndefined();
  });
});
