import { describe, expect, it } from "vitest";

import {
  isPreviewModelSelectable,
  previewChosenModelReset,
  previewDisplayModel,
  previewModelNeedsConfirm,
  previewStartQuery,
  previewTurnCost,
} from "./previewChatModel";

const MODELS = [
  { id: "gemini" as const, isDefault: true },
  { id: "haiku_writer" as const, isDefault: false },
  { id: "opus" as const, isDefault: false },
];

/** 서버가 그 모델 하나를 공개 목록에서 뺀 목록 — 상위 모델 총 스위치는 켜진 채다. */
const MODELS_WITHOUT_OPUS = MODELS.filter((model) => model.id !== "opus");

describe("previewDisplayModel", () => {
  it("목록에 있는 모델을 골랐으면 그 모델이 화면의 모델이다", () => {
    expect(previewDisplayModel(["chat_premium_models"], "opus", MODELS)).toBe("opus");
    expect(previewDisplayModel(["chat_premium_models"], "gemini", MODELS)).toBe("gemini");
  });

  // 총 스위치는 켜진 채 그 모델 하나만 공개 목록에서 빠지면 서버는 기본 모델로 답한다. 화면도 그래야 칩·잔량·단가가 맞다.
  it("고른 모델이 목록에서 빠지면 기능이 켜져 있어도 기본 모델이다", () => {
    expect(previewDisplayModel(["chat_premium_models"], "opus", MODELS_WITHOUT_OPUS)).toBe("gemini");
  });

  // 목록이 오기 전에는 세션의 기능 목록(총 스위치)으로만 정한다.
  it("목록이 없으면 기능이 켜져 있을 때만 고른 모델이다", () => {
    expect(previewDisplayModel(["chat_premium_models"], "opus", undefined)).toBe("opus");
    expect(previewDisplayModel([], "opus", undefined)).toBe("gemini");
    expect(previewDisplayModel(undefined, "opus", undefined)).toBe("gemini");
    expect(previewDisplayModel([], "gemini", undefined)).toBe("gemini");
  });
});

describe("previewChosenModelReset", () => {
  // 되돌리지 않으면 그 모델이 다시 공개될 때 다음 세션이 확인 없이 더 비싼 모델로 열린다.
  it("고른 모델이 목록에서 빠지면 기본 모델로 되돌린다", () => {
    expect(previewChosenModelReset(MODELS_WITHOUT_OPUS, "opus")).toBe("gemini");
  });

  it("고른 모델이 목록에 있으면 그대로 둔다", () => {
    expect(previewChosenModelReset(MODELS, "opus")).toBeUndefined();
    expect(previewChosenModelReset(MODELS, "gemini")).toBeUndefined();
  });

  it("목록이 없거나 비면 판정하지 않는다", () => {
    expect(previewChosenModelReset(undefined, "opus")).toBeUndefined();
    expect(previewChosenModelReset([], "opus")).toBeUndefined();
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
  it("세션이 없을 때 기본 모델이 아닌 모델로 가면 클로버 사용 동의를 묻는다", () => {
    expect(previewModelNeedsConfirm(MODELS, "opus", false)).toBe(true);
    expect(previewModelNeedsConfirm(MODELS, "haiku_writer", false)).toBe(true);
  });

  it("세션이 없을 때 기본 모델로 가면 묻지 않는다 — 대화방과 같다", () => {
    expect(previewModelNeedsConfirm(MODELS, "gemini", false)).toBe(false);
  });

  // 기본 모델인지 정할 수 없으면 묻는 쪽이다 — 묻지 않고 비싼 모델로 가는 것보다 한 번 더 묻는 것이 낫다.
  it("목록이 없으면 묻는다", () => {
    expect(previewModelNeedsConfirm(undefined, "gemini", false)).toBe(true);
  });

  it("세션이 있으면 기본 모델이 아닌 모델로 가도 묻는다", () => {
    expect(previewModelNeedsConfirm(MODELS, "opus", true)).toBe(true);
  });

  // 돈 때문이 아니라 진행 중인 미리보기 대화를 잃기 때문에 묻는다.
  it("세션이 있으면 기본 모델로 돌아가는 것도 묻는다", () => {
    expect(previewModelNeedsConfirm(MODELS, "gemini", true)).toBe(true);
  });
});

describe("previewStartQuery", () => {
  // 서버의 쿼리 기본값이 기본 모델이라 싣지 않아도 같다.
  it("기본 모델이면 쿼리를 싣지 않는다", () => {
    expect(previewStartQuery(MODELS, "gemini")).toBeUndefined();
  });

  it("기본 모델이 아니면 그 모델을 쿼리로 싣는다", () => {
    expect(previewStartQuery(MODELS, "opus")).toEqual({ model: "opus" });
    expect(previewStartQuery(MODELS, "haiku_writer")).toEqual({ model: "haiku_writer" });
  });

  it("목록이 없어 기본 모델인지 모르면 고른 모델을 싣는다", () => {
    expect(previewStartQuery(undefined, "gemini")).toEqual({ model: "gemini" });
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
