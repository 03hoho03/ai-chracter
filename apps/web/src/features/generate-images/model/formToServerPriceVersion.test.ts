import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import type { GenerateImagesFormValues } from "./schema";

const VALUES: GenerateImagesFormValues = {
  prompt: "1girl, solo",
  model: "v1",
  style: "soft_portrait",
  aspectRatio: "1:1",
  count: 1,
  reference: null,
};

// 가격 버전도 서버 스키마에서 선택 칸이라 빼먹어도 컴파일이 잡지 못한다.
describe("formToServer의 가격 버전", () => {
  it("화면이 본 가격 버전을 싣는다", () => {
    expect(formToServer(VALUES, { isReferenceEnabled: false, priceVersion: 2 }).priceVersion).toBe(2);
  });

  it("가격 버전을 모르면(가격표를 아직 못 받았거나 옛 서버) 칸을 싣지 않는다", () => {
    const body = formToServer(VALUES, { isReferenceEnabled: false, priceVersion: undefined });
    expect("priceVersion" in body).toBe(false);
  });
});
