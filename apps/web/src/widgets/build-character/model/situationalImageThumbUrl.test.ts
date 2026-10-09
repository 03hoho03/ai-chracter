import { describe, expect, it } from "vitest";

import { situationalImageThumbUrl } from "./situationalImageThumbUrl";

const SAVED = [
  { id: "row-1", imageAssetId: "asset-1", imageUrl: "https://cdn/asset-1_thumb.webp" },
  { id: "row-2", imageAssetId: "asset-2", imageUrl: "https://cdn/asset-2_thumb.webp" },
];

describe("situationalImageThumbUrl", () => {
  it("shows nothing when the row has no image", () => {
    expect(situationalImageThumbUrl({ itemId: "row-1", image: null, local: undefined, saved: SAVED })).toBeNull();
  });

  it("uses the saved url of the same row and the same asset", () => {
    expect(
      situationalImageThumbUrl({ itemId: "row-2", image: { assetId: "asset-2" }, local: undefined, saved: SAVED }),
    ).toBe("https://cdn/asset-2_thumb.webp");
  });

  // 그림을 바꾼 직후에는 응답이 아직 옛 자산을 보고 있다. 행 id 만 맞는 주소를 쓰면 옛 그림이 보인다.
  it("ignores the saved url when the row's asset has changed since the last save", () => {
    expect(
      situationalImageThumbUrl({ itemId: "row-1", image: { assetId: "asset-new" }, local: undefined, saved: SAVED }),
    ).toBeNull();
  });

  // 같은 자산이라도 다른 행의 주소는 쓰지 않는다.
  it("ignores a saved url that belongs to another row", () => {
    expect(
      situationalImageThumbUrl({ itemId: "row-3", image: { assetId: "asset-1" }, local: undefined, saved: SAVED }),
    ).toBeNull();
  });

  it("prefers the local copy of the same asset over the saved url", () => {
    expect(
      situationalImageThumbUrl({
        itemId: "row-1",
        image: { assetId: "asset-1" },
        local: { assetId: "asset-1", url: "blob:local-1" },
        saved: SAVED,
      }),
    ).toBe("blob:local-1");
  });

  it("ignores a local copy of an asset the row no longer holds", () => {
    expect(
      situationalImageThumbUrl({
        itemId: "row-1",
        image: { assetId: "asset-1" },
        local: { assetId: "asset-old", url: "blob:old" },
        saved: SAVED,
      }),
    ).toBe("https://cdn/asset-1_thumb.webp");
  });

  // 이 칸이 생기기 전 서버의 응답에는 주소가 없다.
  it("shows nothing when the saved row carries no url", () => {
    expect(
      situationalImageThumbUrl({
        itemId: "row-1",
        image: { assetId: "asset-1" },
        local: undefined,
        saved: [{ id: "row-1", imageAssetId: "asset-1" }],
      }),
    ).toBeNull();
  });
});
