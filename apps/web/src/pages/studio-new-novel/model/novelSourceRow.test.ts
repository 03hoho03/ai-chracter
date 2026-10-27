import { describe, expect, it } from "vitest";

import { toNovelSourceRowAction } from "./novelSourceRow";

describe("toNovelSourceRowAction", () => {
  it("소설이 없고 막히지 않은 방은 새로 만든다", () => {
    expect(toNovelSourceRowAction({ novelId: null, novelCreationBlocked: false })).toEqual({ kind: "create" });
  });

  it("소설이 있고 막히지 않은 방은 그 소설을 연다", () => {
    expect(toNovelSourceRowAction({ novelId: "n1", novelCreationBlocked: false })).toEqual({ kind: "open", novelId: "n1" });
  });

  it("막힌 방은 소설이 없으면 이유만 보인다", () => {
    expect(toNovelSourceRowAction({ novelId: null, novelCreationBlocked: true })).toEqual({ kind: "blocked" });
  });

  it("막힌 방에 이미 만든 소설이 있어도 열기 대신 이유만 보인다", () => {
    expect(toNovelSourceRowAction({ novelId: "n1", novelCreationBlocked: true })).toEqual({ kind: "blocked" });
  });
});
