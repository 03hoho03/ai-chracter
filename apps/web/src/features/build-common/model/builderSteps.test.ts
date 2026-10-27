import { describe, expect, it } from "vitest";

import {
  BUILDER_STEP_IDS,
  BUILDER_STEP_LABELS,
  previewKindFor,
  stepsWithErrors,
  tabForStep,
  tabsInStepOrder,
  tabsOfStep,
  type TabStepTable,
} from "./builderSteps";

// 배열 순서와 묶음 순서가 일부러 어긋난 탭 넷. `c` 는 배열에서 셋째지만 첫 묶음이다.
const TABS = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }] as const;
type TabId = (typeof TABS)[number]["id"];
const TABLE = { a: "basics", b: "opening", c: "basics", d: "publish" } as const satisfies TabStepTable<TabId>;

describe("BUILDER_STEP_IDS", () => {
  it("기본 설정 → 시작 장면 → 테스트 → 공개 준비 순서다", () => {
    expect(BUILDER_STEP_IDS.map((step) => BUILDER_STEP_LABELS[step])).toEqual(["기본 설정", "시작 장면", "테스트", "공개 준비"]);
  });

  // 작성 가이드가 탭 하나를 "N단계"로 부르고 있어, 빌더 묶음 이름에 같은 낱말이 오면 같은 말이 두 뜻이 된다.
  it("묶음 이름에 '단계' 낱말이나 숫자가 없다", () => {
    for (const label of Object.values(BUILDER_STEP_LABELS)) expect(label).not.toMatch(/단계|\d/);
  });
});

describe("tabsInStepOrder", () => {
  it("묶음 순서로 줄 세우고 같은 묶음 안은 배열 순서를 지킨다", () => {
    expect(tabsInStepOrder(TABS, TABLE).map((tab) => tab.id)).toEqual(["a", "c", "b", "d"]);
  });

  it("받은 탭 객체를 그대로 돌려준다(복사본이 아니다)", () => {
    expect(tabsInStepOrder(TABS, TABLE)[1]).toBe(TABS[2]);
  });
});

describe("tabsOfStep", () => {
  it("그 묶음의 탭만 배열 순서로 거른다", () => {
    expect(tabsOfStep(TABS, TABLE, "basics").map((tab) => tab.id)).toEqual(["a", "c"]);
    expect(tabsOfStep(TABS, TABLE, "publish").map((tab) => tab.id)).toEqual(["d"]);
  });
});

describe("tabForStep", () => {
  it("지금 탭이 그 묶음에 있으면 그대로 둔다", () => {
    expect(tabForStep(TABS, TABLE, "basics", "c")).toBe("c");
  });

  it("다른 묶음이면 그 묶음의 첫 탭이다", () => {
    expect(tabForStep(TABS, TABLE, "basics", "d")).toBe("a");
    expect(tabForStep(TABS, TABLE, "opening", "a")).toBe("b");
  });
});

describe("stepsWithErrors", () => {
  it("오류 탭을 품은 묶음만 고른다", () => {
    expect([...stepsWithErrors(new Set(["c", "d"]), TABLE)].sort()).toEqual(["basics", "publish"]);
  });

  it("이 빌더에 없는 탭 id 는 무시한다", () => {
    expect(stepsWithErrors(new Set(["mediaBook"]), TABLE).size).toBe(0);
  });
});

describe("previewKindFor", () => {
  it("테스트를 고른 동안은 카드 탭에서도 대화다", () => {
    expect(previewKindFor("card", true)).toBe("chat");
  });

  it("테스트가 아니면 탭이 정한 것이다", () => {
    expect(previewKindFor("card", false)).toBe("card");
    expect(previewKindFor("chat", false)).toBe("chat");
  });
});
