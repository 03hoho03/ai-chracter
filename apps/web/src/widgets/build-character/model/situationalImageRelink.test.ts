import { describe, expect, it } from "vitest";

import { situationalImageAfterRelink, situationalImageRelinkAction } from "./situationalImageRelink";

describe("situationalImageRelinkAction", () => {
  it("registers the restored image when the row still holds it and has a situation", () => {
    expect(
      situationalImageRelinkAction("asset-1", { image: { assetId: "asset-1" }, situationDescription: "비 오는 날" }),
    ).toBe("register");
  });

  it("skips when the row is gone", () => {
    expect(situationalImageRelinkAction("asset-1", undefined)).toBe("skip");
  });

  // 되살린 뒤 다른 그림을 올렸으면 옛 그림을 등록해 새 그림을 덮으면 안 된다.
  it("skips when the row now holds another image", () => {
    expect(
      situationalImageRelinkAction("asset-1", { image: { assetId: "asset-2" }, situationDescription: "비 오는 날" }),
    ).toBe("skip");
  });

  it("skips when the row no longer has an image", () => {
    expect(situationalImageRelinkAction("asset-1", { image: null, situationDescription: "비 오는 날" })).toBe("skip");
  });

  // 등록 API 는 빈 상황을 받지 않는다. 공백뿐인 상황도 빈 것으로 본다.
  it.each(["", "   \n"])("waits for a situation when it is blank (%j)", (situationDescription) => {
    expect(situationalImageRelinkAction("asset-1", { image: { assetId: "asset-1" }, situationDescription })).toBe(
      "wait-description",
    );
  });
});

describe("situationalImageAfterRelink", () => {
  it("saves once more when the row still holds the registered image", () => {
    expect(situationalImageAfterRelink("asset-1", { assetId: "asset-1" })).toBe("save");
  });

  // 다른 그림의 등록이 먼저 끝났다면 방금 등록이 서버 행을 옛 그림으로 덮었다.
  it("registers the current image when another image arrived meanwhile", () => {
    expect(situationalImageAfterRelink("asset-1", { assetId: "asset-2" })).toBe("register-current");
  });

  it.each([null, undefined])("does nothing when the row has no image (%s)", (currentImage) => {
    expect(situationalImageAfterRelink("asset-1", currentImage)).toBe("none");
  });
});
