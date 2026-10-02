import { describe, expect, it } from "vitest";

import { resolveProfileImageUrl } from "./resolveProfileImageUrl";

describe("resolveProfileImageUrl", () => {
  const savedA = { thumbnailAssetId: "a", thumbnailUrl: "https://s3/a_thumb.webp?sig=1" };
  const noDraft = { thumbnailAssetId: null, thumbnailUrl: null };
  const blobA = { assetId: "a", url: "blob:a", canExpire: false };
  const signedA = { assetId: "a", url: "https://s3/a.webp?sig=pick", canExpire: true };

  it("shows nothing when the form has no image, even if local and saved urls exist", () => {
    expect(resolveProfileImageUrl({ image: null, local: blobA, draft: savedA })).toBeNull();
    expect(resolveProfileImageUrl({ image: null, local: undefined, draft: noDraft })).toBeNull();
  });

  it("prefers a non-expiring local url of the same asset over the saved url", () => {
    expect(resolveProfileImageUrl({ image: { assetId: "a" }, local: blobA, draft: savedA })).toBe("blob:a");
  });

  it("prefers the saved url over an expiring local url of the same asset", () => {
    expect(resolveProfileImageUrl({ image: { assetId: "a" }, local: signedA, draft: savedA })).toBe(savedA.thumbnailUrl);
  });

  it("uses an expiring local url when there is no saved url for that asset", () => {
    expect(resolveProfileImageUrl({ image: { assetId: "a" }, local: signedA, draft: noDraft })).toBe(signedA.url);
    expect(
      resolveProfileImageUrl({ image: { assetId: "a" }, local: signedA, draft: { thumbnailAssetId: "a", thumbnailUrl: null } }),
    ).toBe(signedA.url);
  });

  it("uses the saved url when it describes the form's asset", () => {
    expect(resolveProfileImageUrl({ image: { assetId: "a" }, local: undefined, draft: savedA })).toBe(savedA.thumbnailUrl);
  });

  it("passes through a missing saved url for the same asset", () => {
    expect(resolveProfileImageUrl({ image: { assetId: "a" }, local: undefined, draft: { thumbnailAssetId: "a", thumbnailUrl: null } })).toBeNull();
  });

  it("ignores a local url left over from a different asset", () => {
    const blobB = { assetId: "b", url: "blob:b", canExpire: false };
    expect(resolveProfileImageUrl({ image: { assetId: "a" }, local: blobB, draft: savedA })).toBe(savedA.thumbnailUrl);
    expect(resolveProfileImageUrl({ image: { assetId: "a" }, local: blobB, draft: noDraft })).toBeNull();
  });

  it("does not show the stale saved picture after the form switched to another asset", () => {
    expect(resolveProfileImageUrl({ image: { assetId: "b" }, local: undefined, draft: savedA })).toBeNull();
  });
});
