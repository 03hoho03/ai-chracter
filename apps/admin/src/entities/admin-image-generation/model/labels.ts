import type { components } from "@ai-character-chat/api-types";

// 상태는 서버가 이름 붙인 컴포넌트 스키마가 없어(쿼리
// 파라미터에만 리터럴로 박혀 있다) 이 파일이 상태 값의 단일 소스다. 스타일은 `ImageStylePreset`
// 스키마가 있어 그대로 가져온다.
export type ImageGenerationStatus = "pending" | "succeeded" | "blocked" | "failed";
export type ImageStyle = components["schemas"]["ImageStylePreset"];

export const IMAGE_GENERATION_STATUS_LABELS: Record<ImageGenerationStatus, string> = {
  pending: "대기중",
  succeeded: "성공",
  blocked: "차단됨",
  failed: "실패",
};

// `apps/api/src/api/images/models.py`의 `ImageStyleSpec` 한글 이름과 맞춘다 — 사용자가 생성 화면에서
// 보는 이름과 어드민이 같은 스타일을 다르게 부르면 안 된다.
export const IMAGE_STYLE_LABELS: Record<ImageStyle, string> = {
  soft_portrait: "부드러운",
  chapel_glass: "스테인드",
  royal_drama: "극적",
  sparkle_night: "반짝임",
  watercolor: "수채",
  pixel_art: "픽셀",
  deco_cute: "데포르메",
};

export function isImageGenerationStatus(value: string): value is ImageGenerationStatus {
  return value in IMAGE_GENERATION_STATUS_LABELS;
}

export function isImageStyle(value: string): value is ImageStyle {
  return value in IMAGE_STYLE_LABELS;
}

/** 상태·스타일이 늘면 각 `*_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을 손으로 또 적으면
 * 그 강제가 목록에는 걸리지 않아 새 멤버가 라우트 검증과 필터에서 조용히 빠진다. 그래서 둘 다
 * 키에서 도출한다(`entities/admin-content/model/labels.ts` 동형). */
export const IMAGE_GENERATION_STATUS_VALUES = Object.keys(IMAGE_GENERATION_STATUS_LABELS).filter(
  isImageGenerationStatus,
);
export const IMAGE_STYLE_VALUES = Object.keys(IMAGE_STYLE_LABELS).filter(isImageStyle);

export const IMAGE_GENERATION_STATUS_OPTIONS = IMAGE_GENERATION_STATUS_VALUES.map((value) => ({
  value,
  label: IMAGE_GENERATION_STATUS_LABELS[value],
}));

export const IMAGE_STYLE_OPTIONS = IMAGE_STYLE_VALUES.map((value) => ({
  value,
  label: IMAGE_STYLE_LABELS[value],
}));

/** `AdminImageGenerationListItem.status`/`.style`는 서버 스키마에서 좁은 리터럴이 아니라
 * 평범한 `string`이다(`AdminContentListItem.type`과 달리 응답 모델이 enum을 안 쓴다) — 그래서
 * 목록 렌더는 `Record` 직접 인덱싱(`as` 필요)이 아니라 술어로 좁힌 뒤 폴백하는 이 헬퍼를 쓴다. */
export function imageGenerationStatusLabel(value: string): string {
  return isImageGenerationStatus(value) ? IMAGE_GENERATION_STATUS_LABELS[value] : value;
}

export function imageStyleLabel(value: string): string {
  return isImageStyle(value) ? IMAGE_STYLE_LABELS[value] : value;
}
