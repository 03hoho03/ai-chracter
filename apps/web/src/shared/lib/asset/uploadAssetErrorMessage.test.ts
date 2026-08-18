import { describe, expect, it } from "vitest";

import { UploadAssetError, type UploadAssetErrorCode } from "./uploadAsset";
import { uploadAssetErrorMessage } from "./uploadAssetErrorMessage";

const CODES: UploadAssetErrorCode[] = [
  "FILE_TOO_LARGE",
  "DECODE_FAILED",
  "ENCODE_FAILED",
  "SIZE_LIMIT_EXCEEDED",
  "UPLOAD_FAILED",
];

describe("uploadAssetErrorMessage", () => {
  it("실패 사유마다 서로 다른 문구를 준다", () => {
    const messages = CODES.map((code) => uploadAssetErrorMessage(new UploadAssetError(code, "debug")));

    expect(new Set(messages).size).toBe(CODES.length);
  });

  it("분류되지 않은 에러는 일반 문구로 폴백한다", () => {
    const fallback = uploadAssetErrorMessage(new Error("boom"));

    expect(fallback).toBe("이미지 업로드에 실패했어요. 잠시 후 다시 시도해주세요.");
    expect(CODES.map((code) => uploadAssetErrorMessage(new UploadAssetError(code, "debug")))).not.toContain(
      fallback,
    );
  });
});
