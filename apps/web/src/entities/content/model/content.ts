import type { components } from "@ai-character-chat/api-types";

export type ContentType = components["schemas"]["ContentType"];
export type ContentVisibility = components["schemas"]["ContentVisibility"];
export type ModerationStatus = components["schemas"]["ModerationStatus"];

/** `ContentType` 목록의 단일 소스. 옵션 배열·타입 술어·zod enum이 전부 여기서 도출된다.
 *
 * TS-09의 정석(목록을 두고 `type X = (typeof LIST)[number]`로 타입을 도출)은 여기서 쓸 수 없다 —
 * `ContentType`은 `generated.ts`가 소유하므로 목록 옆으로 옮길 수 없다. 그래서 방향을 뒤집어
 * **목록이 타입 전체를 덮는지**를 아래 한 줄이 컴파일 타임에 강제한다. `as const satisfies
 * readonly ContentType[]`로는 안 된다 — 그건 원소가 멤버인지만 보고 커버리지는 보지 않는다. */
export const CONTENT_TYPES = ["character", "story"] as const;

type AssertNoUncovered<T extends never> = T;
/** `CONTENT_TYPES`가 `ContentType`의 멤버를 빠뜨리면 `Exclude<...>`가 `never`가 아니게 되어
 * `T extends never` 제약을 못 만족하고 **이 줄에서 컴파일이 깨진다**. 지우지 말 것 — 이 파일에서
 * 커버리지를 검사하는 장치는 이것 하나뿐이다(실증: `"story"`를 빼면
 * `error TS2344: Type '"story"' does not satisfy the constraint 'never'`).
 *
 * `no-unused-vars`를 끄는 이유: 타입 레벨 단언이라 **산출물이 값이 아니라 컴파일 에러**다. 쓰이는
 * 곳이 없는 게 정상이고, 쓰이게 만들려면 런타임 항등 함수를 끼워 넣어야 한다. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
type _CoversAllContentTypes = AssertNoUncovered<Exclude<ContentType, (typeof CONTENT_TYPES)[number]>>;

/** 화면에 쓰는 한국어 이름. `Record<ContentType, string>`이라 멤버가 늘면 여기서도 컴파일이 깨진다.
 * (`ProfileContentSection`·`ContentDetailView`에 같은 모양의 지역 `TYPE_LABEL`이 각각 남아 있다 —
 * 이번 런이 건드린 코드가 아니라 옮기지 않았다.) */
export const CONTENT_TYPE_LABEL: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

export function isContentType(value: string): value is ContentType {
  return CONTENT_TYPES.some((contentType) => contentType === value);
}

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
  // BE는 kind==='accessible'이면 visibility를 항상 채워 보낸다. 그래도 단언하지 않는 이유는
  // 계약이 깨졌을 때 `undefined`가 그대로 흘러 "공개범위 없음"으로 렌더되기 때문이다 —
  // 가장 제한적인 값으로 떨어뜨려 **덜 보이는 쪽으로** 실패한다.
  return { kind: "accessible", visibility: raw.visibility ?? "private" };
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
