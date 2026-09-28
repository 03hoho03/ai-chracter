import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import type { GenerateImagesFormValues } from "./schema";

const ASSET_ID = "3f2b8c1e-5d4a-4b6f-9e2a-1c7d8e9f0a1b";

function makeValues(reference: GenerateImagesFormValues["reference"]): GenerateImagesFormValues {
  return { prompt: "1girl, solo", model: "v1", style: "soft_portrait", aspectRatio: "1:1", count: 1, reference };
}

// `referenceAssetId`는 서버 스키마에서 선택 필드라(생성 타입이 `?:`) 이 변환이 빼먹어도 컴파일이
// 잡지 못한다 — 참조가 조용히 빠진 채 참조 없는 이미지가 과금돼 나간다. 그래서 런타임으로 고정한다.
describe("formToServer의 참조 이미지", () => {
  it("참조를 쓸 수 있고 골라 두었으면 그 이미지 id를 싣는다", () => {
    const body = formToServer(makeValues({ assetId: ASSET_ID }), { isReferenceEnabled: true });
    expect(body.referenceAssetId).toBe(ASSET_ID);
  });

  it("참조를 쓸 수 없게 되면 폼에 남은 참조를 싣지 않는다", () => {
    const body = formToServer(makeValues({ assetId: ASSET_ID }), { isReferenceEnabled: false });
    expect("referenceAssetId" in body).toBe(false);
  });

  it("참조를 고르지 않았으면 키 자체를 싣지 않는다", () => {
    const body = formToServer(makeValues(null), { isReferenceEnabled: true });
    expect("referenceAssetId" in body).toBe(false);
  });
});
