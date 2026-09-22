import { describe, expect, it } from "vitest";

import { CLOVER_KIND_LABELS } from "./cloverKindLabel";

describe("CLOVER_KIND_LABELS", () => {
  it("BE CLOVER_KIND_CATEGORY(clover/router.py)의 kind 10종을 전부 덮는다", () => {
    const kinds = [
      "attendance_grant",
      "mission_grant",
      "admin_grant",
      "chat_refund",
      "image_refund",
      "chat_spend",
      "image_spend",
      "expire_burn",
      "admin_revoke",
      "withdrawal_burn",
    ];
    for (const kind of kinds) {
      expect(CLOVER_KIND_LABELS[kind]).toBeTypeOf("string");
    }
  });

  it("모르는 kind는 폴백이 호출부 몫이다(?? key) — 맵 자체는 undefined를 돌려준다", () => {
    expect(CLOVER_KIND_LABELS["never_added"]).toBeUndefined();
  });
});
