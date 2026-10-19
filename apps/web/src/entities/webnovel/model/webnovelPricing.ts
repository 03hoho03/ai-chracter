import type { WebnovelChapterItem } from "../api/useWebnovelQuery";

/** 작품 정보 머리의 가격 한 줄 — "1~5화 무료 · 6화부터 화당 30클로버". 무료 화 수와 가격은 서버 응답을 그대로 받는다
 * (설정값이라 화면이 사본을 갖지 않는다). 공개한 화가 모두 무료 범위 안이면 지금은 살 화가 없다고 말한다.
 *
 * 작가는 무료 범위 뒤의 화도 화마다 무료로 낼 수 있어, 그런 화가 있으면 "…, 일부 화 무료"를 덧붙인다 — 목차의 화별
 * 표식과 어긋나지 않게. 판정은 목차의 `access`(이 사람에게의 상태)다: 무료 범위 뒤인데 `free` 면 작가가 무료로 둔 화다
 * (산 뒤 무료가 된 화도 `free` 로 온다). 무료 범위 뒤 화가 모두 무료면 "모든 화 무료"다. 게시자 본인에게는 이 줄을 쓰지
 * 않는다(그 사람에게는 모든 화가 `publisher` 다). */
export function toWebnovelPriceSummary({
  chapters,
  freeChapterCount,
  chapterPrice,
}: {
  chapters: readonly Pick<WebnovelChapterItem, "ordinal" | "access">[];
  freeChapterCount: number;
  chapterPrice: number;
}): string {
  const afterRange = chapters.filter((chapter) => chapter.ordinal > freeChapterCount);
  const freeAfterRange = afterRange.filter((chapter) => chapter.access === "free").length;
  if (afterRange.length === 0 || freeAfterRange === afterRange.length) return "모든 화 무료";
  const paid = `화당 ${chapterPrice.toLocaleString()}클로버`;
  const tail = freeAfterRange > 0 ? ", 일부 화 무료" : "";
  if (freeChapterCount <= 0) return `${paid}${tail}`;
  return `${toFreeRange(freeChapterCount)} 무료 · ${freeChapterCount + 1}화부터 ${paid}${tail}`;
}

/** 잠긴 화 화면의 설명 — "이 소설은 1~5화가 무료이고, 6화부터는 화마다 소장해서 읽어요." */
export function toLockedChapterSentence(freeChapterCount: number): string {
  if (freeChapterCount <= 0) return "이 소설은 화마다 소장해서 읽어요.";
  return `이 소설은 ${toFreeRange(freeChapterCount)}가 무료이고, ${freeChapterCount + 1}화부터는 화마다 소장해서 읽어요.`;
}

function toFreeRange(freeChapterCount: number): string {
  return freeChapterCount === 1 ? "1화" : `1~${freeChapterCount}화`;
}
