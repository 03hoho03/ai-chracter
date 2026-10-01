import { describe, expect, it } from "vitest";

import { nextThumbnailUrlEntry, THUMBNAIL_URL_REUSE_MS } from "./stableThumbnailUrl";

describe("nextThumbnailUrlEntry", () => {
  const signed = { url: "https://s3/a?sig=1", receivedAt: 0, canExpire: true };

  it("keeps a fresh signed url when the autosave response offers a new one", () => {
    expect(nextThumbnailUrlEntry(signed, "https://s3/a?sig=2", THUMBNAIL_URL_REUSE_MS - 1)).toBe(signed);
  });

  it("switches to the offered url once the kept one is old enough to expire soon", () => {
    expect(nextThumbnailUrlEntry(signed, "https://s3/a?sig=2", THUMBNAIL_URL_REUSE_MS)).toEqual({
      url: "https://s3/a?sig=2",
      receivedAt: THUMBNAIL_URL_REUSE_MS,
      canExpire: true,
    });
  });

  it("never replaces a local object url", () => {
    const local = { url: "blob:x", receivedAt: 0, canExpire: false };

    expect(nextThumbnailUrlEntry(local, "https://s3/a?sig=2", THUMBNAIL_URL_REUSE_MS * 10)).toBe(local);
  });

  it("adopts the first offered url and keeps an old one when nothing new is offered", () => {
    expect(nextThumbnailUrlEntry(undefined, "https://s3/a", 5)).toEqual({ url: "https://s3/a", receivedAt: 5, canExpire: true });
    expect(nextThumbnailUrlEntry(signed, undefined, THUMBNAIL_URL_REUSE_MS * 2)).toBe(signed);
  });

  it("does not re-stamp an aging url when the same url is offered again", () => {
    const aged = nextThumbnailUrlEntry(signed, signed.url, THUMBNAIL_URL_REUSE_MS + 60_000);

    expect(aged).toBe(signed);
    // 그 뒤 새 주소가 오면 곧바로 바뀐다(옛 주소가 다시 "갓 받은 것"이 되어 밀어내지 않는다).
    expect(nextThumbnailUrlEntry(aged, "https://s3/a?sig=2", THUMBNAIL_URL_REUSE_MS + 120_000)?.url).toBe("https://s3/a?sig=2");
  });
});
