export type SearchInputSync = { kind: "keep" } | { kind: "collapse" } | { kind: "fill"; value: string };

/** URL 검색어가 바뀌었을 때 펼친 검색 입력칸을 어떻게 맞출지 정한다.
 *
 * 바뀐 값이 디바운스가 **마지막으로 쓴 값**과 같으면 자기 쓰기가 커밋된 것이라 손대지 않는다 — 입력칸과 비교하면
 * 디바운스가 발사된 뒤 커밋되기 전에 친 글자를 지우게 된다. 다르면 바깥 변경(로고·유형 전환·해시태그·칩 ×·
 * `필터 지우기`·뒤로/앞으로)이라 입력칸이 칩과 다른 말을 하지 않게 맞춘다: 검색어가 없어졌으면 접고, 다른
 * 값이 됐으면 그 값으로 채운다. 접혀 있을 때는 맞출 것이 없다 — 걸린 검색어는 칩이 보이고 펼칠 때 채운다. */
export function resolveSearchInputSync({
  urlQuery,
  lastWrittenQuery,
  inputValue,
  isExpanded,
}: {
  urlQuery: string | undefined;
  lastWrittenQuery: string | undefined;
  inputValue: string;
  isExpanded: boolean;
}): SearchInputSync {
  if (urlQuery === lastWrittenQuery || !isExpanded) return { kind: "keep" };
  const typed = inputValue.trim();
  if (!urlQuery) return typed === "" ? { kind: "keep" } : { kind: "collapse" };
  return typed === urlQuery ? { kind: "keep" } : { kind: "fill", value: urlQuery };
}
