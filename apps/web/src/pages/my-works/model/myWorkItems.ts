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

const UPDATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** 초안 카드의 "… 수정" 표기. `MyPagePage`의 `draftUpdatedAtFormatter`와 같은 포맷이다 —
 * US-013이 그쪽 초안 섹션을 걷어내면 이 하나만 남는다. 호출부는 `toMyWorkMetaLabel` 하나다. */
function formatMyWorkUpdatedAt(updatedAt: string): string {
  return UPDATED_AT_FORMATTER.format(new Date(updatedAt));
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

/**
 * 이 작품에 **아직 발행하지 않은 편집분**이 있는가.
 *
 * 카드의 마이크로카피 한 줄(`toMyWorkMetaLabel`)과 "⋯" 메뉴의 `편집한 내용 버리기`(`MyWorkCardMenu`)가
 * 같은 판정을 쓰게 하는 단일 소스다 — 둘이 갈리면 카드는 버릴 게 없다고 말하는데 메뉴는 버리라고 권하는
 * 상태가 화면에 남는다.
 *
 * 초안은 통째로 미발행이라 "발행분과의 차이"라는 개념 자체가 없다 — 그래서 `false`다(초안 메뉴에는
 * 이 항목이 원래 없고, 대신 `삭제하기`가 있다).
 *
 * `ContentSummary.hasUnpublishedChanges`는 서버가 명시적으로 들고 있는 플래그이고 초안 버전의 존재에서
 * 파생시킨 값이 **아니다**(US-002) — 발행이 다음 편집용 초안을 자동 복제하므로 발행작에는 초안 행이 항상
 * 딸려 있어, 존재만으로는 아무것도 판정할 수 없다.
 */
export function hasUnpublishedEdits(item: MyWorkItem): boolean {
  return item.kind === "published" && item.hasUnpublishedChanges;
}

/**
 * 카드에서 지표와 배지 사이에 놓이는 한 줄. 초안과 발행작이 **서로 다른 것**을 여기에 넣는다.
 *
 * - 초안: `2026-08-20 수정` — 지표가 없어 이 줄이 없으면 제목과 배지 사이가 통째로 비고, 목록의 정렬 키를
 *   화면에서 확인할 방법도 사라진다.
 * - 미발행 편집분이 있는 발행작: 그 사실 + **발행하면 무엇이 달라지는지**. 배지가 아니라 별도 줄인 것은
 *   확정 결정이다(US-010) — 390px 2열에서 카드 내부폭이 139px인데 `이용제한` 배지가 이미 배지 줄을
 *   압박하고, 무엇보다 **배지로는 다음 행동을 말할 수 없다**. 이 PRD의 성공지표가 발행 완료율이라
 *   상태 통보("편집 중이에요")로 끝내면 지표에 닿지 않는다.
 * - 그 밖의 발행작: 없음. 늘 떠 있는 줄은 신호가 아니다.
 *
 * 발행작의 `updatedAt`을 초안처럼 `… 수정`으로 달 수는 없다 — 그건 마지막 **발행** 시각이라(확정 결정 1)
 * 같은 라벨을 붙이면 거짓말이 된다.
 */
export function toMyWorkMetaLabel(item: MyWorkItem): string | undefined {
  if (item.kind === "draft") return `${formatMyWorkUpdatedAt(item.updatedAt)} 수정`;
  // 동사를 `보여요`가 아니라 `반영돼요`로 둔 이유: 비공개 발행작에도 이 줄이 뜨는데 거기서 발행은
  // 남에게 보이게 하는 일이 아니다. `반영`은 세 공개범위 모두에서 참이다.
  return hasUnpublishedEdits(item) ? "편집한 내용은 발행해야 반영돼요" : undefined;
}
