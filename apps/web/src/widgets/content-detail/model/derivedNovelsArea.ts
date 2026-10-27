import { isWebnovelOpen } from "@/entities/session";

/** 원작 상세에서 공개 소설 목록을 부를지. 그 API 는 로그인 회원에게만 열려 있어, 비로그인에게 부르면 401 이 전역 세션
 * 정리를 건드린다 — 홈 노벨 섹션과 같은 조건(로그인 ∧ 노벨이 그 사람에게 열림)일 때만 부른다. */
export function isDerivedNovelsRequestable({
  isLoggedIn,
  pricingEnabled,
  sessionEnabled,
}: {
  isLoggedIn: boolean;
  pricingEnabled: boolean | undefined;
  sessionEnabled: boolean | undefined;
}): boolean {
  return isLoggedIn && isWebnovelOpen(pricingEnabled, sessionEnabled);
}

export type DerivedNovelsArea<T> = { kind: "none" } | { kind: "list"; items: T[]; isHiddenFromOthers: boolean };

/** 공개 소설 영역을 어떻게 그릴지. 항목이 없으면(응답 전·빈 목록) 영역 자체가 없다.
 *
 * `isHiddenFromOthers` 는 원작자 본인에게만 참이다 — 원작자가 목록을 숨겨도 서버는 본인에게 항목을 그대로 주므로, 남에게는
 * 안 보인다는 사실을 따로 알린다. 숨김 여부는 목록 응답의 `visible` 이 아니라 작품 상세의 값으로 읽는다: 숨김 토글은
 * 작품 상세 캐시를 바로 고치지만 목록 캐시는 건드리지 않아, 목록을 다시 받기 전까지 그 응답의 값은 토글 전 값이다. */
export function toDerivedNovelsArea<T>({
  pages,
  isOwner,
  derivedNovelsVisible,
}: {
  pages: readonly { visible?: boolean; items: readonly T[] }[] | undefined;
  isOwner: boolean;
  derivedNovelsVisible: boolean;
}): DerivedNovelsArea<T> {
  const items = (pages ?? []).flatMap((page) => page.items);
  if (items.length === 0) return { kind: "none" };
  return { kind: "list", items, isHiddenFromOthers: isOwner && !derivedNovelsVisible };
}
