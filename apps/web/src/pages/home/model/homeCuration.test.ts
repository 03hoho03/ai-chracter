import { describe, expect, it } from "vitest";

import {
  shouldRestoreResultsFocus,
  toHomeCurationHeading,
  toHomeCurationLayoutKey,
  toHomeCurationView,
} from "./homeCuration";

const item = {
  id: "c1",
  type: "story" as const,
  name: "마지막 주문",
  oneLiner: "문 닫기 십 분 전, 마지막 손님이 들어온다.",
  thumbnailUrl: null,
};

describe("toHomeCurationView", () => {
  it("필터가 없고 지정작이 오면 그 작품을 보인다", () => {
    expect(toHomeCurationView({ isFiltered: false, hasGivenUp: false, isPending: false, item })).toEqual({ kind: "shown", item });
  });

  it("거르는 조건이 하나라도 걸리면 지정작이 있어도 숨긴다", () => {
    expect(toHomeCurationView({ isFiltered: true, hasGivenUp: false, isPending: false, item })).toEqual({ kind: "hidden" });
  });

  it("필터가 걸려 있으면 응답을 기다리지 않는다 — 목록을 붙잡지 않는다", () => {
    expect(toHomeCurationView({ isFiltered: true, hasGivenUp: false, isPending: true, item: null })).toEqual({ kind: "hidden" });
  });

  it("필터 없는 홈에서 응답 전이면 기다린다", () => {
    expect(toHomeCurationView({ isFiltered: false, hasGivenUp: false, isPending: true, item: null })).toEqual({ kind: "waiting" });
  });

  it("기다림을 포기한 뒤에는 응답이 와도, 아직 안 왔어도 그리지 않는다 — 그리드를 이미 먼저 그렸다", () => {
    expect(toHomeCurationView({ isFiltered: false, hasGivenUp: true, isPending: false, item })).toEqual({
      kind: "hidden",
    });
    expect(toHomeCurationView({ isFiltered: false, hasGivenUp: true, isPending: true, item: null })).toEqual({
      kind: "hidden",
    });
  });

  it("지정이 없거나 조회가 실패하면(둘 다 item 이 없다) 섹션을 그리지 않는다", () => {
    expect(toHomeCurationView({ isFiltered: false, hasGivenUp: false, isPending: false, item: null })).toEqual({ kind: "hidden" });
  });
});

describe("toHomeCurationLayoutKey", () => {
  it("기다리는 동안과 정해진 뒤가 다른 값이다 — 정해지는 순간 스켈레톤을 옮기지 않고 갈아 끼운다", () => {
    expect(toHomeCurationLayoutKey({ kind: "waiting" })).not.toBe(toHomeCurationLayoutKey({ kind: "shown", item }));
    expect(toHomeCurationLayoutKey({ kind: "waiting" })).not.toBe(toHomeCurationLayoutKey({ kind: "hidden" }));
  });

  it("정해진 뒤끼리는 같은 값이다 — 필터를 걸고 풀 때(보임↔숨김) 그리드를 다시 만들지 않는다", () => {
    expect(toHomeCurationLayoutKey({ kind: "shown", item })).toBe(toHomeCurationLayoutKey({ kind: "hidden" }));
  });
});

describe("shouldRestoreResultsFocus", () => {
  it("갈아 끼우기 전 포커스가 덩어리 안에 있었고 지금 잃었으면 옮긴다", () => {
    expect(shouldRestoreResultsFocus({ isRemounted: true, wasFocusInside: true, isFocusLost: true })).toBe(true);
  });

  it("셋 중 하나라도 아니면 옮기지 않는다 — 갈아 끼우지 않았거나, 포커스가 덩어리 밖이었거나, 이미 다른 곳에 있다", () => {
    expect(shouldRestoreResultsFocus({ isRemounted: false, wasFocusInside: true, isFocusLost: true })).toBe(false);
    expect(shouldRestoreResultsFocus({ isRemounted: true, wasFocusInside: false, isFocusLost: true })).toBe(false);
    expect(shouldRestoreResultsFocus({ isRemounted: true, wasFocusInside: true, isFocusLost: false })).toBe(false);
  });
});

describe("toHomeCurationHeading", () => {
  it("서비스 이름으로 유형별 제목을 만든다 — 스토리는 '이야기'로 부른다", () => {
    expect(toHomeCurationHeading("story")).toBe("또나가 고른 이야기");
    expect(toHomeCurationHeading("character")).toBe("또나가 고른 캐릭터");
  });
});
