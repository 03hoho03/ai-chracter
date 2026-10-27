import type { ContentWorkItem, NovelWorkPublication, WorkItem } from "@/entities/work";

/**
 * 행의 상태 배지. 뜻은 서버 상태 필터와 같은 정의 하나다 — 배지가 붙은 행이 같은 이름의 필터에서 사라지지 않게.
 *
 * - `draft` 초안: 발행한 적 없는 캐릭터·스토리.
 * - `public` 공개 중: 공개 범위 공개 ∧ 이용제한 아닌 발행작, 또는 독자가 지금 읽을 수 있는 소설.
 * - `published` 발행됨: 공개 중이 아닌 발행작(링크 공개·비공개·이용제한). 공개 범위는 ⋯ 메뉴의 현재값이 말한다.
 * - `changed` 수정본 있음: 발행한 뒤 고친 초안이 있음. 공개 범위·이용제한과 무관하다.
 * - `restricted` 이용제한: 운영자가 내린 작품·소설.
 * - `withdrawn` 공개 거둠, `inReview` 심사 대기, `rejected` 반려: 소설의 노벨 공개 상태.
 * - `hiddenFromReaders` 독자에게 안 보임: 승인된 공개 중인데도 읽을 수 없는 소설(원작 이용제한·공개 화 없음·게시자
 *   정지·판매 중단).
 */
export type StudioStatusBadge =
  | "draft"
  | "public"
  | "published"
  | "changed"
  | "restricted"
  | "withdrawn"
  | "inReview"
  | "rejected"
  | "hiddenFromReaders";

export function toStudioStatusBadges(item: WorkItem): StudioStatusBadge[] {
  if (item.kind === "novel") return item.publication === null ? [] : [toNovelBadge(item.publication)];
  if (!item.hasPublished) return ["draft"];

  const isRestricted = item.moderationStatus === "restricted";
  const badges: StudioStatusBadge[] = [item.visibility === "public" && !isRestricted ? "public" : "published"];
  if (isRestricted) badges.push("restricted");
  if (item.hasUnpublishedChanges) badges.push("changed");
  return badges;
}

/** 소설 공개 상태 하나. 순서는 작품 정보의 공개 절과 같다 — 운영 이용제한이 가장 앞서고, 첫 공개의 대기·반려는 공개
 * 범위가 거둠이어도 대기·반려로 보인다. 공개 중은 응답의 `readable` 하나만 본다(서버의 공개 중 필터와 같은 판정).
 *
 * 작품 정보의 공개 절은 첫 공개 승인 정책이 꺼져 있으면 남은 대기·반려 행을 "공개 거둠"으로 그리는데, 목록 응답에는 그
 * 정책 값이 없어 여기서는 대기·반려로 그린다. 정책이 켜진 동안에는 둘이 같다. */
function toNovelBadge(publication: NovelWorkPublication): StudioStatusBadge {
  if (publication.moderationStatus === "restricted") return "restricted";
  if (publication.reviewStatus === "pending") return "inReview";
  if (publication.reviewStatus === "rejected") return "rejected";
  if (publication.visibility === "withdrawn") return "withdrawn";
  return publication.readable ? "public" : "hiddenFromReaders";
}

export type StudioActionTarget =
  | { kind: "builder"; type: ContentWorkItem["kind"]; id: string }
  | { kind: "novel"; id: string };

export type StudioNextAction = { label: string; target: StudioActionTarget };

/** 행과 이어 만들기 카드가 여는 곳과 그 라벨. 행 전체가 이 링크 하나다. 캐릭터·스토리는 발행작이든 초안이든 같은
 * 빌더 주소로 간다(발행하면 편집용 초안이 딸려 있다) — 라벨만 지금 할 일로 갈린다. 이용제한 작품은 고친 내용이 있어도
 * 공개할 수 없어 "공개 준비"가 아니라 "수정하기"다. 소설은 공개 상태·화 목록·보드 진입을 함께 가진 작품 정보로 간다. */
export function toStudioNextAction(item: WorkItem): StudioNextAction {
  if (item.kind === "novel") return { label: "소설 열기", target: { kind: "novel", id: item.id } };

  const target: StudioActionTarget = { kind: "builder", type: item.kind, id: item.id };
  if (!item.hasPublished) return { label: "이어 쓰기", target };
  if (item.hasUnpublishedChanges && item.moderationStatus !== "restricted") return { label: "공개 준비", target };
  return { label: "수정하기", target };
}

/** 행에 보이는 이름. 이름을 아직 안 정한 초안은 내 작품 화면과 같은 자리 문구, 제목 없는 소설은 원작 제목이다. */
export function toStudioWorkTitle(item: WorkItem): string {
  if (item.kind === "novel") return item.title || item.contentTitle;
  return item.title || "제목 없는 초안";
}

/** 행의 썸네일 주소. 없으면 유형 아이콘 자리로 그린다. */
export function toStudioThumbnailUrl(item: WorkItem): string | null {
  return item.kind === "novel" ? item.cover.url : item.thumbnailUrl;
}
