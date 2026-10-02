import { describe, expect, it } from "vitest";

import { createBuilderUiState, indexOpenKey } from "./builderUiState";

describe("createBuilderUiState", () => {
  it("기본은 접힘이고 두 번 토글하면 원래대로다", () => {
    const state = createBuilderUiState();
    expect(state.isOpen("stat:a")).toBe(false);
    state.toggle("stat:a");
    expect(state.isOpen("stat:a")).toBe(true);
    state.toggle("stat:a");
    expect(state.isOpen("stat:a")).toBe(false);
  });

  it("open 은 이미 열린 것을 닫지 않는다", () => {
    const state = createBuilderUiState();
    state.toggle("stat:a");
    state.open(["stat:a", "stat:b"]);
    expect(state.isOpen("stat:a")).toBe(true);
    expect(state.isOpen("stat:b")).toBe(true);
  });

  it("인덱스 키 항목을 지우면 그 열림은 사라지고 뒤 항목의 열림이 한 칸씩 당겨진다", () => {
    const state = createBuilderUiState();
    state.open([0, 1, 3].map((index) => indexOpenKey("developmentExample", index)));
    state.open([indexOpenKey("exampleDialogue", 2)]);
    state.removeIndexKey("developmentExample", 1);
    expect([0, 1, 2, 3].map((index) => state.isOpen(indexOpenKey("developmentExample", index)))).toEqual([
      true,
      false,
      true,
      false,
    ]);
    expect(state.isOpen(indexOpenKey("exampleDialogue", 2))).toBe(true);
  });

  it("바뀐 것이 없으면 구독자에게 알리지 않는다", () => {
    const state = createBuilderUiState();
    state.open(["stat:a"]);
    let calls = 0;
    state.subscribe(() => {
      calls += 1;
    });
    state.open(["stat:a"]);
    state.close("stat:b");
    state.select("startingSetup", undefined);
    expect(calls).toBe(0);
    state.open(["stat:b"]);
    expect(calls).toBe(1);
  });

  it("선택 값은 이름별로 따로 산다", () => {
    const state = createBuilderUiState();
    state.select("startingSetup", "setup-b");
    expect(state.getSelection("startingSetup")).toBe("setup-b");
    expect(state.getSelection("other")).toBeUndefined();
    state.select("startingSetup", undefined);
    expect(state.getSelection("startingSetup")).toBeUndefined();
  });
});
