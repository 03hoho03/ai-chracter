import { describe, expect, it } from "vitest";

import { restoreUnderLimit } from "./restoreDecision";

describe("restoreUnderLimit", () => {
  it("상한보다 적으면 그대로 되살린다", () => {
    expect(restoreUnderLimit(4, "x", 5, "최대 5개예요.")).toEqual({ kind: "restore", item: "x" });
  });

  it("이미 상한이면 되살리지 않는다(되살리면 상한을 넘는다)", () => {
    expect(restoreUnderLimit(5, "x", 5, "최대 5개예요.")).toEqual({ kind: "refuse", reason: "최대 5개예요." });
  });
});
