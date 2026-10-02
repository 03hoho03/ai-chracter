import { describe, expect, it } from "vitest";

import { MESSAGE_BY_CODE } from "@/shared/lib/asset/uploadAssetErrorMessage";

import { isFileDrag, pickDroppedImage } from "./mediaBookImageFile";

function imageFile(name: string, type: string): File {
  return new File(["x"], name, { type });
}

describe("pickDroppedImage", () => {
  it("picks the one dropped file when it is a PNG, JPEG or WebP image", () => {
    for (const type of ["image/png", "image/jpeg", "image/webp"]) {
      const file = imageFile("유나_리딩", type);
      expect(pickDroppedImage([file])).toEqual({ ok: true, file });
    }
  });

  it("refuses several files and points to the bulk upload by name instead of using the first", () => {
    const result = pickDroppedImage([imageFile("a.png", "image/png"), imageFile("b.png", "image/png")]);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.message).toContain("파일 이름으로 한꺼번에 넣기");
  });

  it("refuses a format the file picker would not offer, even one the browser can decode", () => {
    expect(pickDroppedImage([imageFile("움짤.gif", "image/gif")])).toEqual({
      ok: false,
      message: MESSAGE_BY_CODE.DECODE_FAILED,
    });
    expect(pickDroppedImage([imageFile("메모.txt", "text/plain")]).ok).toBe(false);
  });

  it("refuses a drop that carries no file", () => {
    expect(pickDroppedImage([]).ok).toBe(false);
  });
});

describe("isFileDrag", () => {
  it("is true only while files are being dragged, not text or page elements", () => {
    expect(isFileDrag(["Files"])).toBe(true);
    expect(isFileDrag(["text/plain", "text/uri-list"])).toBe(false);
    expect(isFileDrag([])).toBe(false);
  });
});
