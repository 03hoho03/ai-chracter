import { describe, expect, it } from "vitest";

import { chapterModelCost, hasChapterModelChoice, initialChapterModelId } from "./chapterModel";

const GEMINI = { id: "gemini", name: "Gemini", chapterGenerate: 40, chapterRegenerate: 41 } as const;
const SONNET = { id: "sonnet", name: "Claude Sonnet 4.6", chapterGenerate: 160, chapterRegenerate: 160 } as const;

describe("hasChapterModelChoice", () => {
  // 상위 모델 허용이 없으면 목록은 기본 모델 하나다 — 그때 선택이 보이면 화면이 이 기능 전과 달라진다.
  it("모델이 하나뿐이면 선택을 그리지 않는다", () => {
    expect(hasChapterModelChoice([GEMINI])).toBe(false);
    expect(hasChapterModelChoice([])).toBe(false);
    expect(hasChapterModelChoice([GEMINI, SONNET])).toBe(true);
  });
});

describe("initialChapterModelId", () => {
  it("직전에 쓴 모델이 목록에 있으면 그 모델이다", () => {
    expect(initialChapterModelId([GEMINI, SONNET], "sonnet")).toBe("sonnet");
  });

  // 허용을 거둔 뒤의 옛 값이 남아 있어도 고를 수 없는 모델을 골라 두지 않는다.
  it("직전 모델이 목록에 없으면 목록 맨 앞이다", () => {
    expect(initialChapterModelId([GEMINI], "opus")).toBe("gemini");
    expect(initialChapterModelId([GEMINI, SONNET], undefined)).toBe("gemini");
  });

  it("목록이 비면 기본 모델이다 — 요청에는 늘 모델을 싣는다", () => {
    expect(initialChapterModelId([], undefined)).toBe("gemini");
  });
});

describe("chapterModelCost", () => {
  it("고른 모델의 생성·재생성 가격을 갈라 읽는다", () => {
    expect(chapterModelCost([GEMINI, SONNET], "gemini", "generate", 0)).toBe(40);
    expect(chapterModelCost([GEMINI, SONNET], "gemini", "regenerate", 0)).toBe(41);
    expect(chapterModelCost([GEMINI, SONNET], "sonnet", "generate", 0)).toBe(160);
  });

  it("목록에 없으면 서버가 따로 준 기본 모델 가격이다", () => {
    expect(chapterModelCost([], "gemini", "regenerate", 40)).toBe(40);
  });
});
