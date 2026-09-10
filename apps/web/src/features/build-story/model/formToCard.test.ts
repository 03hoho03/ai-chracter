import { describe, expect, it } from "vitest";

import { formToCard } from "./formToCard";
import type { StoryBuilderFormValues } from "./schema";

function baseFormValues(): StoryBuilderFormValues {
  return {
    profile: { name: "여름밤의 항해", oneLiner: "바다 위 표류기", image: { assetId: "asset-thumbnail" } },
    storySetting: {
      promptTemplate: "basic",
      worldSetting: "근미래 해양 도시",
      developmentExamples: [],
      userGoal: undefined,
      rules: undefined,
      customPrompt: undefined,
    },
    startingSetups: [],
    keywordNotes: [],
    shortcuts: [],
    registration: {
      description: "표류한 선원들의 생존기",
      genre: null,
      target: null,
      hashtags: [],
      visibility: "private",
    },
  };
}

describe("formToCard", () => {
  it("profile.name을 title로, ctx의 thumbnailUrl/authorNickname을 카드 props로 옮긴다", () => {
    const card = formToCard(baseFormValues(), {
      thumbnailUrl: "https://cdn.example.com/thumb.webp",
      authorNickname: "항해자",
    });

    expect(card.title).toBe("여름밤의 항해");
    expect(card.thumbnailUrl).toBe("https://cdn.example.com/thumb.webp");
    expect(card.author).toEqual({ name: "항해자", profileUrl: "" });
  });

  it("발행 전이라 metrics는 0, tags엔 story·unpublished가 함께 달린다", () => {
    const card = formToCard(baseFormValues(), { thumbnailUrl: null, authorNickname: "항해자" });

    expect(card.metrics).toEqual({ viewCount: 0 });
    expect(card.tags).toEqual(["story", "unpublished"]);
  });

  it("이름이 비어 있는(필수 누락) 초안도 빈 제목 카드로 만든다 — 발행 전 검증은 이 함수의 몫이 아니다", () => {
    const values = baseFormValues();
    values.profile.name = "";

    expect(formToCard(values, { thumbnailUrl: null, authorNickname: "항해자" }).title).toBe("");
  });

  it("썸네일이 아직 없으면 null을 그대로 전달한다", () => {
    const card = formToCard(baseFormValues(), { thumbnailUrl: null, authorNickname: "항해자" });

    expect(card.thumbnailUrl).toBeNull();
  });

  it("긴 제목도 자르지 않고 그대로 전달한다(말줄임은 ContentCard의 CSS 몫)", () => {
    const longTitle = "가".repeat(200);
    const values = baseFormValues();
    values.profile.name = longTitle;

    expect(formToCard(values, { thumbnailUrl: null, authorNickname: "항해자" }).title).toBe(longTitle);
  });

  it("onClick은 항상 존재하는, 아무 일도 하지 않는 함수다 — 프리뷰 카드는 눌러도 갈 상세 페이지가 없다", () => {
    const card = formToCard(baseFormValues(), { thumbnailUrl: null, authorNickname: "항해자" });

    expect(() => card.onClick()).not.toThrow();
  });
});
