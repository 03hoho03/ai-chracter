import { describe, expect, it } from "vitest";

import { toForgetFailure, toPreviewFailure } from "./forgetFailure";

function apiError(status: number, detail: unknown) {
  return { status, detail, message: "x" };
}

describe("toForgetFailure", () => {
  it("treats a memory that is already gone as stale, so the list is fetched again", () => {
    expect(toForgetFailure(apiError(404, { code: "MEMORY_ITEM_NOT_FOUND" }), "forget")).toEqual({
      kind: "gone",
      message: "이미 잊었거나 바뀐 기억이에요. 목록을 다시 불러왔어요.",
    });
  });

  it("tells the panel the switch was turned off, so the memory response is fetched again", () => {
    expect(toForgetFailure(apiError(404, { code: "MEMORY_ITEMS_DISABLED" }), "preview")).toEqual({
      kind: "disabled",
      message: "지금은 기억을 보거나 잊게 할 수 없어요.",
    });
  });

  it("falls back to a sentence for what could not be done", () => {
    expect(toForgetFailure(apiError(500, undefined), "forget")).toEqual({
      kind: "message",
      message: "잊게 하지 못했어요. 잠시 후 다시 시도해 주세요.",
    });
    expect(toForgetFailure(new Error("network"), "preview")).toEqual({
      kind: "message",
      message: "함께 잊을 장면을 확인하지 못했어요. 다시 확인해 주세요.",
    });
  });

  it("does not read a room-missing 404 as a missing memory", () => {
    expect(toForgetFailure(apiError(404, "Chat room not found"), "forget").kind).toBe("message");
  });
});

describe("toPreviewFailure", () => {
  it("closes on a memory that is already gone, because asking again can never succeed", () => {
    expect(toPreviewFailure(apiError(404, { code: "MEMORY_ITEM_NOT_FOUND" }))).toEqual({
      kind: "gone",
      message: "이미 잊었거나 바뀐 기억이에요. 목록을 다시 불러왔어요.",
    });
  });

  it("closes when the switch was turned off, so the panel falls back to its plain view", () => {
    expect(toPreviewFailure(apiError(404, { code: "MEMORY_ITEMS_DISABLED" }))).toEqual({
      kind: "disabled",
      message: "지금은 기억을 보거나 잊게 할 수 없어요.",
    });
  });

  it("offers asking again only for network and server errors", () => {
    const retry = { kind: "retry", message: "함께 잊을 장면을 확인하지 못했어요. 다시 확인해 주세요." };
    expect(toPreviewFailure(new Error("network"))).toEqual(retry);
    expect(toPreviewFailure(apiError(0, undefined))).toEqual(retry);
    expect(toPreviewFailure(apiError(503, undefined))).toEqual(retry);
  });

  it("stops without a retry for other refusals", () => {
    for (const error of [apiError(403, { code: "X" }), apiError(404, "Chat room not found"), apiError(422, undefined)]) {
      expect(toPreviewFailure(error)).toEqual({
        kind: "stopped",
        message: "지금은 이 사실을 잊게 할 수 없어요. 대화 상자를 닫고 목록을 다시 확인해 주세요.",
      });
    }
  });
});
