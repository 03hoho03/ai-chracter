import type { components } from "@ai-character-chat/api-types";

export type ContentType = components["schemas"]["ContentType"];
export type ContentVisibility = components["schemas"]["ContentVisibility"];
export type ModerationStatus = components["schemas"]["ModerationStatus"];

export type ContentAccessStatus =
  | { kind: "accessible"; visibility: ContentVisibility }
  | { kind: "restricted" }
  | { kind: "deleted" };

/** techspec-content-versioning.md §1 — 공개범위(제작자 설정)와 모더레이션 상태(관리자 설정)를
 * 오버레이하는 단일 진실 공급원. 상태 태그를 그리는 화면은 항상 이 함수를 거친다. */
export function resolveAccessStatus(
  visibility: ContentVisibility,
  moderationStatus: ModerationStatus,
): ContentAccessStatus {
  if (moderationStatus === "deleted") return { kind: "deleted" };
  if (moderationStatus === "restricted") return { kind: "restricted" };
  return { kind: "accessible", visibility };
}
