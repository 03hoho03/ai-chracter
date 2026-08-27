import type { components } from "@ai-character-chat/api-types";

export type ContentType = components["schemas"]["ContentType"];
export type ContentVisibility = components["schemas"]["ContentVisibility"];
export type ModerationStatus = components["schemas"]["ModerationStatus"];

/** `GET /contents`(techspec-home-discovery.md §1)의 sort 쿼리 파라미터 — 별도 named schema가 아니라
 * OpenAPI 오퍼레이션의 인라인 유니언이라 여기서 직접 선언한다. */
export type ContentListSort = "latest" | "popular" | "genre";

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

/** 홈/검색/타인 프로필 노출 가드(techspec-content-versioning.md §1, FR-9/FR-69) — accessible이면서 public인 콘텐츠만. */
export function canDiscoverPublicly(access: ContentAccessStatus): boolean {
  return access.kind === "accessible" && access.visibility === "public";
}

/** 기존 대화방 재접속 가드(FR-86) — visibility와 무관하게 restricted/deleted일 때만 차단. */
export function canAccessExistingRoom(moderationStatus: ModerationStatus): boolean {
  return moderationStatus !== "restricted" && moderationStatus !== "deleted";
}

/** 상세화면/신규 진입 가드(US-019) — canAccessExistingRoom과 규칙이 달라 별도 함수로 둔다.
 * 타입 술어로 만들지 말 것 — `accessible + private + 비소유자`도 false라, 거짓 분기를
 * `restricted | deleted`로 좁히는 술어는 불건전하다(`ContentUnavailableState`가 그 반례를 다룬다). */
export function canViewDetailPage(access: ContentAccessStatus, isOwner: boolean): boolean {
  if (access.kind === "restricted" || access.kind === "deleted") return false;
  if (access.visibility === "private") return isOwner;
  return true;
}

/** `GET /contents/{id}`가 내려주는 평평한(optional visibility) accessStatus를 이 판별 유니언으로
 * 변환한다(BE는 kind==='accessible'일 때 항상 visibility를 함께 채워 보낸다). */
export function toContentAccessStatus(raw: {
  kind: "accessible" | "restricted" | "deleted";
  visibility?: ContentVisibility | null;
}): ContentAccessStatus {
  if (raw.kind !== "accessible") return { kind: raw.kind };
  return { kind: "accessible", visibility: raw.visibility as ContentVisibility };
}

/** 카드 상태 배지 — 공개범위와 이용제한을 **함께** 낸다(이용제한이어도 공개범위 배지는 남는다).
 * `/my`와 프로필이 같은 작품에 같은 배지 조합을 보여야 해서 두 화면이 이 함수 하나를 거친다(US-008) —
 * 원래 결함이 정확히 "같은 데이터를 그리는 두 화면이 서로 다른 말을 한다"였고, 프로필만 이 판정을
 * 갖고 있었다. 반환 타입은 `ContentCardTag`의 부분집합이라 호출부가 `[type, ...이것]`으로 펼친다.
 *
 * `deleted`는 내지 않는다 — 목록 엔드포인트가 소유자에게도 삭제분을 거르므로 카드 자체가 안 온다. */
export function toContentStatusTags(content: {
  visibility: ContentVisibility;
  moderationStatus: ModerationStatus;
}): (ContentVisibility | "restricted")[] {
  const access = resolveAccessStatus(content.visibility, content.moderationStatus);
  return access.kind === "restricted" ? [content.visibility, "restricted"] : [content.visibility];
}
