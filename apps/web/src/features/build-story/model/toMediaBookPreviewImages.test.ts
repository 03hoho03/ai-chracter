import { describe, expect, it } from "vitest";

import { toMediaBookPreviewImages } from "./toMediaBookPreviewImages";
import type { MediaBookCellValues } from "./schema";

function cell(overrides: Partial<MediaBookCellValues> = {}): MediaBookCellValues {
  return {
    id: "AAAAAAAA-0000-0000-0000-000000000001",
    personId: "11111111-0000-0000-0000-000000000001",
    sceneId: "22222222-0000-0000-0000-000000000001",
    imageAssetId: "asset-1",
    situationDescription: "",
    unlockHint: "",
    excludeFromChat: false,
    ...overrides,
  };
}

describe("toMediaBookPreviewImages", () => {
  it("keys images by the lower-case cell id and takes the size from the form first", () => {
    const images = toMediaBookPreviewImages(
      [cell({ imageWidth: 600, imageHeight: 800 })],
      (_assetId, fallback) => fallback ?? "blob:local",
      new Map([["asset-1", { width: 1, height: 1 }]]),
    );
    expect(images).toEqual({ "aaaaaaaa-0000-0000-0000-000000000001": { url: "blob:local", width: 600, height: 800 } });
  });

  it("falls back to the size from the latest save, then leaves it unknown", () => {
    const resolve = () => "https://cdn/x.webp";
    expect(
      Object.values(toMediaBookPreviewImages([cell()], resolve, new Map([["asset-1", { width: 1024, height: 768 }]]))),
    ).toEqual([{ url: "https://cdn/x.webp", width: 1024, height: 768 }]);
    expect(Object.values(toMediaBookPreviewImages([cell()], resolve, new Map()))).toEqual([
      { url: "https://cdn/x.webp", width: undefined, height: undefined },
    ]);
  });

  it("leaves out cells without an address", () => {
    expect(toMediaBookPreviewImages([cell()], () => undefined, new Map())).toEqual({});
  });
});
