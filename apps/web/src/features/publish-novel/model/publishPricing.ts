import type { NovelPublicationStatus } from "@/entities/novel";

/** 공개 모달 "화별 가격" 목록의 한 줄(노벨 정책 스위치가 켜졌을 때만 그린다).
 *
 * - `choice`: 새로 공개하는 화 — 무료·유료를 고른다.
 * - `locked`: 새로 공개하는 화지만 전에 무료로 공개한 번호라 무료로만 낼 수 있다(지웠다 다시 만든 화).
 * - `kept`: 다시 내는 고친 화 — 지금 가격을 그대로 둔다(`price` 0 = 무료). 무료로 바꾸기는 공개 절의 "무료로 전환"이
 *   하고, 무료 화는 유료가 되지 않는다.
 *
 * 앞 화(무료 화 수까지)는 늘 무료라 줄을 두지 않는다. */
export type PublishPriceRow =
  | { kind: "choice"; ordinal: number }
  | { kind: "locked"; ordinal: number }
  | { kind: "kept"; ordinal: number; price: number };

/** 끝 화를 `targetOrdinal` 로 골랐을 때의 가격 목록(번호 순). 끝 화를 줄이면 새 화 줄도 줄어든다. */
export function toPublishPriceRows(
  status: Pick<
    NovelPublicationStatus,
    "publishedChapterCount" | "publishedChapters" | "freeLockedOrdinals" | "changedChapterOrdinals"
  >,
  { freeChapterCount, targetOrdinal }: { freeChapterCount: number; targetOrdinal: number },
): PublishPriceRow[] {
  const published = status.publishedChapterCount;
  const priceByOrdinal = new Map(status.publishedChapters.map((chapter) => [chapter.ordinal, chapter.price]));
  const kept = toRepublishOrdinals(status).flatMap((ordinal): PublishPriceRow[] => {
    const price = priceByOrdinal.get(ordinal);
    return ordinal > freeChapterCount && price !== undefined ? [{ kind: "kept", ordinal, price }] : [];
  });
  const locked = new Set(status.freeLockedOrdinals);
  const fresh: PublishPriceRow[] = [];
  for (let ordinal = Math.max(published, freeChapterCount) + 1; ordinal <= targetOrdinal; ordinal += 1) {
    fresh.push(locked.has(ordinal) ? { kind: "locked", ordinal } : { kind: "choice", ordinal });
  }
  return [...kept, ...fresh];
}

/** 이번 공개에서 다시 내는 고친 화 번호(오름차순) — 변경 요약을 받을 화다. 공개한 범위 밖의 고친 화는 새 화로 나간다. */
export function toRepublishOrdinals(
  status: Pick<NovelPublicationStatus, "publishedChapterCount" | "changedChapterOrdinals">,
): number[] {
  return status.changedChapterOrdinals
    .filter((ordinal) => ordinal <= status.publishedChapterCount)
    .sort((a, b) => a - b);
}

/** 작품 정보 공개 절 "화별 가격" 목록의 줄 — 공개한 화 중 앞 화를 뺀 것(번호 순), `price` 0 = 무료. */
export function toPublishedPriceRows(
  publishedChapters: NovelPublicationStatus["publishedChapters"],
  freeChapterCount: number,
): NovelPublicationStatus["publishedChapters"] {
  return publishedChapters.filter((chapter) => chapter.ordinal > freeChapterCount).sort((a, b) => a.ordinal - b.ordinal);
}
