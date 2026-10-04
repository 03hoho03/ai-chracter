import { describe, expect, it } from "vitest";

import { getGenerateButtonState, getResultTileLabel } from "./generateButtonState";

const NONE = { isSubmitting: false, isModelsPending: false, isJobInProgress: false };

describe("getGenerateButtonState", () => {
  it("아무것도 진행 중이 아니면 열려 있다", () => {
    expect(getGenerateButtonState(NONE)).toEqual({ isBlocked: false, isGenerating: false });
  });

  it("모델 목록 로딩은 잠그지만 '생성 중'으로 보이지 않는다", () => {
    expect(getGenerateButtonState({ ...NONE, isModelsPending: true })).toEqual({
      isBlocked: true,
      isGenerating: false,
    });
  });

  it("202 전 제출 중에도 잠기고 '생성 중'이다", () => {
    expect(getGenerateButtonState({ ...NONE, isSubmitting: true })).toEqual({
      isBlocked: true,
      isGenerating: true,
    });
  });

  it("잡이 끝나기 전이면 잠기고 '생성 중'이다", () => {
    expect(getGenerateButtonState({ ...NONE, isJobInProgress: true })).toEqual({
      isBlocked: true,
      isGenerating: true,
    });
  });
});

describe("getResultTileLabel", () => {
  it("몇 번째 칸인지를 1부터 세어 이름에 담는다", () => {
    expect(getResultTileLabel(1, 2)).toBe("생성 결과 1/2 상세 보기");
    expect(getResultTileLabel(2, 2)).toBe("생성 결과 2/2 상세 보기");
  });
});
