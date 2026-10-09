/** 무한 스크롤로 받은 페이지들을 한 목록으로 펴되 같은 작품은 처음 나온 자리에만 둔다. 서버 커서는 정렬 키(좋아요 수·
 * 공개 시각)가 페이지를 받는 사이에 바뀐 작품을 다음 페이지에서 다시 줄 수 있다 — 같은 작품이 두 줄이면 React key 도
 * 겹친다. */
export function toUniqueWebnovels<T extends { id: string }>(pages: readonly { items: readonly T[] }[]): T[] {
  const seen = new Set<string>();
  const unique: T[] = [];
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      unique.push(item);
    }
  }
  return unique;
}
