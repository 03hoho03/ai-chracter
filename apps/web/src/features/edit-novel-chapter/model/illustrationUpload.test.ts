import { describe, expect, it } from "vitest";

import { UploadAssetError } from "@/shared/api/asset/uploadAsset";
import { ApiErrorObject } from "@/shared/api/client";

import { ILLUSTRATION_CROP_ASPECTS, toIllustrationUploadErrorMessage } from "./illustrationUpload";

function apiError(status: number, detail: string) {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("toIllustrationUploadErrorMessage", () => {
  // 서버는 소설 삽화로 움직이는 그림을 받지 않고 업로드 완료에서 떨어뜨린다 — 일반 실패 문구("잠시 후 다시")로 접으면
  // 같은 파일로 다시 시도하게 된다.
  it("움직이는 그림 거절은 정지 그림을 고르라고 말한다", () => {
    expect(toIllustrationUploadErrorMessage(apiError(400, "Novel illustrations must be still images"))).toBe(
      "움직이는 그림은 삽화로 올릴 수 없어요. 정지 그림을 골라 주세요.",
    );
  });

  it("다른 업로드 실패는 공용 업로드 문구 그대로다", () => {
    expect(toIllustrationUploadErrorMessage(new UploadAssetError("FILE_TOO_LARGE", "big"))).toBe(
      "15MB가 넘는 사진은 올릴 수 없어요. 더 작은 사진을 선택해주세요.",
    );
    expect(toIllustrationUploadErrorMessage(apiError(400, "Uploaded object is not a decodable image"))).toBe(
      "이미지 업로드에 실패했어요. 잠시 후 다시 시도해주세요.",
    );
  });
});

describe("ILLUSTRATION_CROP_ASPECTS", () => {
  // 기본은 원본이다 — 고르지 않으면 작가가 올린 그림이 잘리지 않고 그대로 선다.
  it("원본·3:4·1:1·4:3 이고 원본이 처음이다", () => {
    expect(ILLUSTRATION_CROP_ASPECTS.map((choice) => choice.label)).toEqual(["원본", "3:4", "1:1", "4:3"]);
    expect(ILLUSTRATION_CROP_ASPECTS[0]?.ratio).toBe("original");
  });
});
