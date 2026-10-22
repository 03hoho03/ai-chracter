import type { PreparedUpload } from "@/shared/api/asset/uploadAsset";
import { isApiError } from "@/shared/api/client";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";

import type { IllustrationSource } from "./boardIllustrations";

/** 출처 창에서 고른 그림. 내 이미지·원작 그림은 이미 있는 자산이고, 기기에서 고른 그림은 자른 파일이라 이 화면이 올린다
 * (올리는 동안 진행을 그 버튼에 보이려고). */
export type PickedIllustrationImage =
  | { kind: "asset"; assetId: string; source: Exclude<IllustrationSource, "upload"> }
  | { kind: "file"; upload: PreparedUpload };

/** 출처 하나의 창을 열어 그림을 고르게 한다(고르지 않고 닫으면 `undefined`). 창들은 화면 위쪽 층이 연다 — 이 화면은 어느 출처를
 * 골랐는지와, 바꾸기면 지금 그림을 넘긴다. */
export type PickIllustrationImage = (
  source: IllustrationSource,
  options: { currentAssetId?: string },
) => Promise<PickedIllustrationImage | undefined>;

/** 삽화 업로드의 자르기 비율. 기본은 원본이다 — 고르지 않으면 작가가 올린 그림이 잘리지 않고 그대로 선다. 세로로 긴 폰 화면
 * 캡처처럼 높이 상한에서 작게 서는 그림은 3:4 로 잘라 크게 세울 수 있다. */
export const ILLUSTRATION_CROP_ASPECTS: readonly { label: string; ratio: number | "original" }[] = [
  { label: "원본", ratio: "original" },
  { label: "3:4", ratio: 3 / 4 },
  { label: "1:1", ratio: 1 },
  { label: "4:3", ratio: 4 / 3 },
];

/** 서버가 소설 삽화 업로드를 움직이는 그림이라 떨어뜨릴 때의 `detail`. 코드가 없는 문자열이라 그대로 견준다. */
const STILL_IMAGE_REJECTION_DETAIL = "Novel illustrations must be still images";

/** 삽화 업로드 실패 → 문구. 움직이는 그림 거절은 따로 말한다 — 공용 일반 문구("잠시 후 다시")로 접으면 같은 파일로 다시
 * 시도하게 된다. 화면은 올리기 전에 정지 그림으로 바꿔 올리므로 대개는 닿지 않는다. */
export function toIllustrationUploadErrorMessage(error: unknown): string {
  if (isApiError(error) && error.status === 400 && error.detail === STILL_IMAGE_REJECTION_DETAIL) {
    return "움직이는 그림은 삽화로 올릴 수 없어요. 정지 그림을 골라 주세요.";
  }
  return uploadAssetErrorMessage(error);
}
