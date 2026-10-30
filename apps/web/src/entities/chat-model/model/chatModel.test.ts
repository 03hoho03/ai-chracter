import { describe, expect, it } from "vitest";

import { defaultChatModelId, defaultChatTurnCost, isDefaultChatModel, type ChatModelId } from "./chatModel";

/** `isDefault` 칸이 없던 서버의 응답 — 생성 타입은 그 칸을 필수로 적어 타입 단언으로만 만들 수 있다. */
function legacyModels(ids: ChatModelId[]): { id: ChatModelId; isDefault: boolean }[] {
  return ids.map((id) => ({ id }) as unknown as { id: ChatModelId; isDefault: boolean });
}

describe("defaultChatModelId", () => {
  // 순서가 아니라 서버가 표시한 칸으로 고른다 — 기본 모델이 맨 앞이 아니어도 그 항목이다.
  it("서버가 기본으로 표시한 항목의 id 다", () => {
    expect(
      defaultChatModelId([
        { id: "opus", isDefault: false },
        { id: "gemini", isDefault: true },
      ]),
    ).toBe("gemini");
  });

  // 칸이 없는 서버로 되돌려도 기본 모델이 "기본이 아님"이 되지 않게 첫 항목으로 대신한다(서버는 기본 모델을 맨 앞에 둔다).
  it("칸이 없는 옛 응답이면 첫 항목이다", () => {
    expect(defaultChatModelId(legacyModels(["gemini", "opus"]))).toBe("gemini");
  });

  it("목록이 없거나 비면 undefined 다", () => {
    expect(defaultChatModelId(undefined)).toBeUndefined();
    expect(defaultChatModelId([])).toBeUndefined();
  });
});

describe("isDefaultChatModel", () => {
  const models = [
    { id: "gemini" as const, isDefault: true },
    { id: "haiku_writer" as const, isDefault: false },
    { id: "opus" as const, isDefault: false },
  ];

  it("기본 모델만 참이다", () => {
    expect(isDefaultChatModel(models, "gemini")).toBe(true);
    expect(isDefaultChatModel(models, "haiku_writer")).toBe(false);
    expect(isDefaultChatModel(models, "opus")).toBe(false);
  });

  it("옛 응답에서도 첫 항목이 기본 모델이다", () => {
    expect(isDefaultChatModel(legacyModels(["gemini", "opus"]), "gemini")).toBe(true);
    expect(isDefaultChatModel(legacyModels(["gemini", "opus"]), "opus")).toBe(false);
  });

  // 목록이 없으면 판정을 지어내지 않는다 — 확인을 붙일지는 호출부가 정한다.
  it("목록이 없으면 undefined 다", () => {
    expect(isDefaultChatModel(undefined, "gemini")).toBeUndefined();
  });
});

describe("defaultChatTurnCost", () => {
  // 빌더 미리보기는 늘 기본 모델이다 — 목록 순서가 아니라 id 로 고른다(상위 모델이 앞에 와도 그 값을 집지 않게).
  it("목록에서 기본 모델 항목의 가격을 고른다", () => {
    expect(
      defaultChatTurnCost([
        { id: "opus", turnCost: 65 },
        { id: "gemini", turnCost: 10 },
      ]),
    ).toBe(10);
  });

  it("목록이 없으면 undefined 다 — 숫자를 지어내지 않는다", () => {
    expect(defaultChatTurnCost(undefined)).toBeUndefined();
    expect(defaultChatTurnCost([{ id: "opus", turnCost: 120 }])).toBeUndefined();
  });
});
