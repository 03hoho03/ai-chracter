import { describe, expect, it } from "vitest";

import { UploadAssetError, type UploadAssetErrorCode } from "@/shared/api/asset/uploadAsset";

import { MESSAGE_BY_CODE, uploadAssetErrorMessage } from "./uploadAssetErrorMessage";

// `MESSAGE_BY_CODE`가 `Record<UploadAssetErrorCode, string>`이라 모든 코드를 담고 있음을 타입이
// 보장한다 — 여기서 다시 나열하면 `UploadAssetErrorCode`에 멤버가 늘 때 이 목록만 뒤처질 수 있다(TS-09).
const CODES = Object.keys(MESSAGE_BY_CODE) as UploadAssetErrorCode[];

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
