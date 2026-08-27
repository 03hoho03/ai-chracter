import {
  toContentStatusTags,
  type ContentCardTag,
  type ContentSummary,
  type VisibilityFilter,
} from "@/entities/content";
import type { DraftSummary } from "@/entities/draft";

import type { MyWorkTypeFilter } from "./myWorksSearch";

/** 내 작품 목록의 한 줄. 발행작(`GET /users/{me}/contents`)과 미발행 초안(`GET /me/drafts`)은 서로 다른
 * 엔드포인트에서 오지만 `id`/`type`/`name`/`thumbnailUrl`/`updatedAt` 다섯 필드를 같은 이름으로 갖고 있어,
 * 좁힘 없이 공통 필드를 읽고 `kind`로만 갈라진다. 지표·공개범위는 발행작에만 있다. */
export type MyWorkItem =
  | ({ kind: "published" } & ContentSummary)
  | ({ kind: "draft" } & DraftSummary);

const updatedAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** 초안 카드의 "… 수정" 표기. `MyPagePage`의 `draftUpdatedAtFormatter`와 같은 포맷이다 —
 * US-013이 그쪽 초안 섹션을 걷어내면 이 하나만 남는다. */
export function formatMyWorkUpdatedAt(updatedAt: string): string {
  return updatedAtFormatter.format(new Date(updatedAt));
}

/**
 * 발행작과 초안을 한 목록으로 합쳐 최근 수정 순으로 세운다.
 *
 * 발행작의 `updatedAt`은 `Content.updated_at`이 아니라 **현재 발행 버전의 `published_at`**이다(US-001 —
 * `Content.updated_at`에는 `onupdate`가 없어 갱신되지 않는다). 서버가 목록마다 이미 그 키로 정렬해 주지만
 * 캐릭터·스토리·초안 세 응답을 클라이언트에서 합치므로 여기서 한 번 더 세운다.
 *
 * 동률은 `id` 내림차순으로 끊는다 — 서버의 `Content.id.desc()`와 같은 규칙이라 한 목록 안에서 순서가
 * 흔들리지 않는다(같은 트랜잭션에서 만들어진 시드 데이터는 시각이 완전히 같다).
 */
export function mergeMyWorks(published: ContentSummary[], drafts: DraftSummary[]): MyWorkItem[] {
  const items: MyWorkItem[] = [
    ...published.map((content): MyWorkItem => ({ kind: "published", ...content })),
    ...drafts.map((draft): MyWorkItem => ({ kind: "draft", ...draft })),
  ];

  return items.sort((a, b) => {
    const byUpdatedAt = Date.parse(b.updatedAt) - Date.parse(a.updatedAt);
    if (byUpdatedAt !== 0) return byUpdatedAt;
    return b.id.localeCompare(a.id);
  });
}

/**
 * 병합된 목록을 필터 칩 한 축(`type`)과 공개 여부 한 축(`visibility`)으로 좁힌다.
 *
 * `미등록`은 초안만, 나머지는 **발행작만** 돌려준다 — FR-18이 "`전체`에는 초안을 포함하지 않는다"로
 * 못박았다. 초안에는 공개범위가 없으므로 `미등록`에서는 `visibility`를 보지 않는다(호출부가 칩 전환 시
 * 파라미터를 함께 비우지만, 손으로 URL을 만든 경우까지 여기서 무해하게 만든다).
 */
export function filterMyWorks(
  items: MyWorkItem[],
  { type, visibility }: { type: MyWorkTypeFilter; visibility: VisibilityFilter },
): MyWorkItem[] {
  if (type === "unpublished") return items.filter((item) => item.kind === "draft");

  return items.filter((item) => {
    if (item.kind !== "published") return false;
    if (type !== "all" && item.type !== type) return false;
    return visibility === "all" || item.visibility === visibility;
  });
}

/** 화면 뒤에 있는 페이징 스트림 셋. 발행작은 유형별로 엔드포인트 호출이 갈리고(`GET /users/{me}/contents`의
 * `type`), 초안은 그 축이 없는 별개 엔드포인트다 — 그래서 커서도 셋이다. */
export type MyWorkPageSource = "character" | "story" | "draft";

/**
 * 칩 하나가 "더 보기"에서 **어느 스트림의 다음 페이지를 당기는지**.
 *
 * `filterMyWorks`가 그 칩에서 무엇을 남기는지와 짝이 맞아야 한다 — 어긋나면 "더 보기"가 화면에 보이지도
 * 않는 목록을 늘리거나(과다), 스크롤 끝에서 남은 페이지를 못 가져온다(과소). 그 짝은 테스트가 지킨다.
 *
 * `전체`가 둘인 것이 이 함수의 존재 이유다: 캐릭터·스토리는 **각각 페이징된 뒤 `mergeMyWorks`가
 * 클라이언트에서 합치므로** 한쪽만 진행시키면 다른 쪽이 24건에서 멈춘 채 목록이 늘어난다.
 */
export function toMyWorkPageSources(type: MyWorkTypeFilter): MyWorkPageSource[] {
  if (type === "unpublished") return ["draft"];
  if (type === "all") return ["character", "story"];
  return [type];
}

/**
 * 카드에 다는 배지 — 타입 하나 + 상태.
 *
 * 발행작의 상태는 `toContentStatusTags`가 정한다. 프로필 카드와 **같은 함수**를 거치게 한 것이 이
 * 함수의 존재 이유다(US-008) — 원래 여기가 `[type, visibility]`만 반환해서, 이용제한 작품이 프로필에서는
 * `이용제한`을 달고 `/my`에서는 `공개`를 달았다. 사본이 둘이면 다시 갈라진다.
 *
 * 초안에는 공개범위가 없다 — 배지는 `미등록` 하나뿐이다(확정 결정 6).
 */
export function toMyWorkTags(item: MyWorkItem): ContentCardTag[] {
  if (item.kind !== "published") return [item.type, "unpublished"];
  return [item.type, ...toContentStatusTags(item)];
}
