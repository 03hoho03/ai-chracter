import type { ContentType, HomeCurationItem } from "@/entities/content";
import { SITE_NAME } from "@/shared/config/site";

/** 홈 큐레이션 섹션이 지금 무엇을 그리는가.
 * - `hidden`: 그리지 않는다.
 * - `waiting`: 응답 전이다 — 홈은 이 동안 목록 그리드도 스켈레톤으로 붙잡아, 섹션이 뒤늦게 끼어들며 그리드를
 *   밀어 내리지 않게 한다. 붙잡는 시간에는 상한이 있다(`curationWaitCap.ts`).
 * - `shown`: 그 작품을 그린다. */
export type HomeCurationView = { kind: "hidden" } | { kind: "waiting" } | { kind: "shown"; item: HomeCurationItem };

/** 섹션은 거르는 조건(장르·검색어·작가·해시태그)이 하나도 없는 홈에서만 보인다 — 정렬은 순서만 바꾸므로 무관하다.
 * 조건이 걸려 있으면 응답을 기다리지도 않는다(목록을 붙잡을 이유가 없다). `item` 이 없으면 지정이 없거나 조회가
 * 실패한 것이고, 어느 쪽이든 섹션 없이 목록만 보인다. `hasGivenUp` 은 기다림이 상한을 넘겨 그리드를 먼저 그렸다는
 * 뜻이라, 그 뒤에 응답이 와도 그리지 않는다(이미 그린 그리드를 밀어 내리지 않게). */
export function toHomeCurationView({
  isFiltered,
  hasGivenUp,
  isPending,
  item,
}: {
  isFiltered: boolean;
  hasGivenUp: boolean;
  isPending: boolean;
  item: HomeCurationItem | null;
}): HomeCurationView {
  if (isFiltered || hasGivenUp) return { kind: "hidden" };
  if (isPending) return { kind: "waiting" };
  if (item === null) return { kind: "hidden" };
  return { kind: "shown", item };
}

/** 큐레이션 섹션 + 결과 영역 덩어리의 React `key`. 큐레이션이 정해지기 전(`waiting`)과 정해진 뒤가 서로 다른 값이라,
 * 정해지는 순간 덩어리가 통째로 새 노드가 된다 — 기다리며 그려 둔 스켈레톤이 섹션에 밀려 내려가는 대신 사라지고
 * 새로 생기므로 브라우저가 레이아웃 이동으로 세지 않는다. 정해진 뒤(보임·숨김·포기)끼리는 같은 값이라, 필터를 걸고
 * 푸는 동안 그리드를 다시 만들지 않는다. */
export function toHomeCurationLayoutKey(view: HomeCurationView): "deciding" | "decided" {
  return view.kind === "waiting" ? "deciding" : "decided";
}

/** 덩어리를 갈아 끼운 직후 결과 영역으로 포커스를 옮겨야 하는가. 갈아 끼웠고(`isRemounted`), 그 전에 포커스가 덩어리
 * 안에 있었고(`wasFocusInside`), 지금 포커스를 잃었을(`<body>`) 때만이다 — 덩어리 밖의 포커스나, 이미 다른 곳으로
 * 옮겨진 포커스는 건드리지 않는다. */
export function shouldRestoreResultsFocus({
  isRemounted,
  wasFocusInside,
  isFocusLost,
}: {
  isRemounted: boolean;
  wasFocusInside: boolean;
  isFocusLost: boolean;
}): boolean {
  return isRemounted && wasFocusInside && isFocusLost;
}

/** 섹션 제목은 스토리를 "이야기"로 부른다 — 유형 이름(`CONTENT_TYPE_LABEL`)과 말이 달라 그 상수를 빌려 쓰지 않는다. */
const CURATION_NOUN: Record<ContentType, string> = {
  story: "이야기",
  character: "캐릭터",
};

export function toHomeCurationHeading(type: ContentType): string {
  return `${SITE_NAME}가 고른 ${CURATION_NOUN[type]}`;
}
