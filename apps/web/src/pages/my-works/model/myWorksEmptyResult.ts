import { koreanParticle } from "@/shared/lib/text/koreanParticle";

/** 목록에 볼 것이 있는데 지금 조건으로는 0건일 때 무엇을 말하고 무엇을 권할지.
 *
 * - `noPublished`: 검색도 칩 필터도 안 걸렸다 — 가진 게 초안뿐이라는 뜻이라 `미등록 보기`를 권한다.
 * - `noMatch`: 걸린 조건이 있다. 칩 필터가 하나라도 걸렸으면 `필터 모두 해제` 하나가 검색어까지 함께 비우고,
 *   검색만 걸렸으면 `검색어 지우기`다 — 버튼 둘을 나란히 두면 둘 다 누르는 것과 하나만 누르는 것의 차이를
 *   사용자가 따져야 한다. */
export type MyWorksEmptyResult =
  | { kind: "noPublished" }
  | { kind: "noMatch"; message: string; action: "clearQuery" | "resetAll" };

/**
 * @param q 정규화된 검색어(`normalizeMyWorksQuery`를 거친 값). 없으면 검색이 안 걸린 것이다.
 * @param filterLabel 걸린 칩 필터를 이름으로 적은 말(`캐릭터 · 비공개`). 칩 필터가 없으면 `undefined`.
 * @param hasMore 아직 안 불러온 페이지가 남았는가. 공개범위는 서버가 아니라 화면이 거르므로 불러온 만큼에서
 *   0건이어도 다음 페이지에는 있을 수 있다 — 그때는 문장의 범위를 불러온 만큼으로 좁힌다.
 */
export function resolveMyWorksEmptyResult({
  q,
  filterLabel,
  hasMore,
}: {
  q: string | undefined;
  filterLabel: string | undefined;
  hasMore: boolean;
}): MyWorksEmptyResult {
  if (q === undefined && filterLabel === undefined) return { kind: "noPublished" };

  const action = filterLabel === undefined ? "clearQuery" : "resetAll";
  const scope = toMyWorksScopeLabel({ q, filterLabel });

  if (hasMore) return { kind: "noMatch", message: `지금까지 불러온 작품 중에는 ${scope}에 해당하는 게 없어요.`, action };
  // 검색만 걸렸을 때는 "해당하는"이 아니라 "찾은"이다 — 사용자가 한 일이 찾기였으므로. 조사는 검색어의 끝 글자에
  // 맞춘다(`'목욕탕'으로`, `'바다'로`). 끝이 한글이 아니면 받침을 알 수 없어 `으로(로)`가 된다.
  if (q !== undefined && filterLabel === undefined) {
    return { kind: "noMatch", message: `'${q}'${koreanParticle(q, "으로/로")} 찾은 작품이 없어요.`, action };
  }
  return { kind: "noMatch", message: `${scope}에 해당하는 작품이 없어요.`, action };
}

/** 건수 줄의 머리. 걸린 조건을 전부 이름으로 적어야 `0건`이 "작품이 하나도 없다"로 읽히지 않는다 —
 * 검색어도 그 조건 중 하나다. 아무것도 안 걸렸을 때만 `전체`다. */
export function toMyWorksScopeLabel({
  q,
  filterLabel,
}: {
  q: string | undefined;
  filterLabel: string | undefined;
}): string {
  const parts = [q === undefined ? undefined : `'${q}'`, filterLabel].filter((part) => part !== undefined);
  return parts.length === 0 ? "전체" : parts.join(" · ");
}
