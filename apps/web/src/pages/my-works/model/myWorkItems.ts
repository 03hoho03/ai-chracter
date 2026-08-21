import type { ContentSummary } from "@/entities/content";
import type { DraftSummary } from "@/entities/draft";

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
