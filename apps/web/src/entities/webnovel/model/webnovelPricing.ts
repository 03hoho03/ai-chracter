/** 작품 정보 머리의 가격 한 줄 — "1~5화 무료 · 6화부터 화당 30클로버". 무료 화 수와 가격은 서버 응답을 그대로 받는다
 * (설정값이라 화면이 사본을 갖지 않는다). 공개한 화가 모두 무료 범위 안이면 지금은 살 화가 없다고 말한다. */
export function toWebnovelPriceSummary({
  chapterCount,
  freeChapterCount,
  chapterPrice,
}: {
  chapterCount: number;
  freeChapterCount: number;
  chapterPrice: number;
}): string {
  const paid = `화당 ${chapterPrice.toLocaleString()}클로버`;
  if (freeChapterCount <= 0) return paid;
  if (chapterCount <= freeChapterCount) return "모든 화 무료";
  return `${toFreeRange(freeChapterCount)} 무료 · ${freeChapterCount + 1}화부터 ${paid}`;
}

/** 잠긴 화 화면의 설명 — "이 소설은 1~5화가 무료이고, 6화부터는 화마다 소장해서 읽어요." */
export function toLockedChapterSentence(freeChapterCount: number): string {
  if (freeChapterCount <= 0) return "이 소설은 화마다 소장해서 읽어요.";
  return `이 소설은 ${toFreeRange(freeChapterCount)}가 무료이고, ${freeChapterCount + 1}화부터는 화마다 소장해서 읽어요.`;
}

function toFreeRange(freeChapterCount: number): string {
  return freeChapterCount === 1 ? "1화" : `1~${freeChapterCount}화`;
}
