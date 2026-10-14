/** 세 목록이 도착한(또는 자리표시를 받은) 뒤 본문에 무엇을 그릴지.
 *
 * - `nothingMade`: 만든 작품이 정말 하나도 없다 — 툴바 없이 만들기만 권하는 화면.
 * - `awaiting`: 지금 조건으로 보일 게 0건인데 그 0건이 **이전 검색어의 자리표시**에서 나왔다. 응답이 오기 전에는
 *   아무 결론도 말하지 않고(빈 상태 문구 대신 카드 자리만 깐다) 툴바는 그대로 둔다. 자리표시로 결론을 내면
 *   0건 검색을 지울 때 "아직 만든 작품이 없어요" 화면이 번쩍이고, 그 화면에는 툴바가 없어 방금 검색 칸으로 옮겨 둔
 *   포커스가 `<body>`로 떨어진다.
 * - `emptyResult`: 응답이 왔고 지금 조건으로 0건이다.
 * - `list`: 보일 게 있다. 자리표시여도 그대로 보인다(입력 중 목록이 사라지지 않게).
 */
export type MyWorksBodyView = "nothingMade" | "awaiting" | "emptyResult" | "list";

/**
 * @param itemCount 세 목록을 합친 건수(칩으로 거르기 전).
 * @param visibleCount 칩·공개범위로 거른 뒤 보일 건수.
 * @param q 정규화된 검색어. 있으면 0건이어도 "만든 게 없다"가 아니라 "찾은 게 없다"다.
 * @param isShowingPlaceholder 세 목록 중 하나라도 이전 검색어의 자리표시를 보여주는 중인가.
 */
export function resolveMyWorksBodyView({
  itemCount,
  visibleCount,
  q,
  isShowingPlaceholder,
}: {
  itemCount: number;
  visibleCount: number;
  q: string | undefined;
  isShowingPlaceholder: boolean;
}): MyWorksBodyView {
  if (visibleCount > 0) return "list";
  if (isShowingPlaceholder) return "awaiting";
  if (itemCount === 0 && q === undefined) return "nothingMade";
  return "emptyResult";
}
