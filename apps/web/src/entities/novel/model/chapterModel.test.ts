import { describe, expect, it } from "vitest";

import {
  hasChapterModelChoice,
  initialChapterModelId,
  toProposalModelOptions,
  toRegenerateModelOptions,
  type ChapterModelOption,
} from "./chapterModel";

const GEMINI: ChapterModelOption = { id: "gemini", name: "Gemini", cost: 120, disabledReason: undefined };
const SONNET: ChapterModelOption = { id: "sonnet", name: "Claude Sonnet", cost: 315, disabledReason: undefined };
const OPUS_DISABLED: ChapterModelOption = {
  id: "opus",
  name: "Claude Opus",
  cost: 510,
  disabledReason: "대화가 길어 이 모델로는 못 써요",
};

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

  // 비활성 항목을 골라 둔 채 열면 금액은 보이는데 실행하면 서버가 409 로 막는다.
  it("직전 모델이 이 묶음에 맞지 않으면 고를 수 있는 첫 모델이다", () => {
    expect(initialChapterModelId([GEMINI, OPUS_DISABLED], "opus")).toBe("gemini");
    expect(initialChapterModelId([{ ...GEMINI, disabledReason: "x" }, SONNET], undefined)).toBe("sonnet");
  });

  it("고를 수 있는 모델이 없으면 기본 모델이다 — 요청에는 늘 모델을 싣는다", () => {
    expect(initialChapterModelId([], undefined)).toBe("gemini");
    expect(initialChapterModelId([OPUS_DISABLED], "opus")).toBe("gemini");
  });
});

describe("toRegenerateModelOptions", () => {
  it("서버가 계산한 묶음 금액을 그대로 싣는다 — 화면이 화 수와 단가를 곱하지 않는다", () => {
    const options = toRegenerateModelOptions([
      { model: "gemini", name: "Gemini", cost: 120, eligible: true, ineligibleReason: null },
    ]);
    expect(options).toEqual([{ id: "gemini", name: "Gemini", cost: 120, disabledReason: undefined }]);
  });

  it("맞지 않는 모델은 빼지 않고 이유 한 줄과 함께 비활성으로 둔다", () => {
    const options = toRegenerateModelOptions([
      { model: "sonnet", name: "Claude Sonnet", cost: 315, eligible: false, ineligibleReason: "too_many_turns" },
      { model: "opus", name: "Claude Opus", cost: 510, eligible: false, ineligibleReason: "too_many_episodes" },
      { model: "gemini", name: "Gemini", cost: 120, eligible: false, ineligibleReason: null },
    ]);
    expect(options.map((option) => option.disabledReason)).toEqual([
      "대화가 길어 이 모델로는 못 써요",
      "화가 많아 이 모델로는 못 써요",
      "이 모델로는 못 써요",
    ]);
  });
});

describe("toProposalModelOptions", () => {
  // 새 화의 금액은 끝 턴을 골라야 정해진다 — 모델 항목에 화 단가를 금액처럼 보이면 고른 뒤 금액과 어긋난다.
  it("모델 항목에 금액을 싣지 않는다", () => {
    const options = toProposalModelOptions([{ id: "opus", name: "Claude Opus", chapterGenerate: 170, chapterRegenerate: 170 }]);
    expect(options).toEqual([{ id: "opus", name: "Claude Opus", cost: undefined, disabledReason: undefined }]);
  });
});
