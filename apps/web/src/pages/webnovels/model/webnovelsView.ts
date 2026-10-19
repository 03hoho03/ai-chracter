import type { WebnovelListSort } from "@/entities/webnovel";

/** 노벨 목록 화면의 칩 — 정렬 둘과 내가 소장한 노벨. 소장은 정렬이 아니라 다른 목록이지만 한 번에 하나만 보이므로 같은
 * 칩 줄에 둔다(새 화면·새 내비 항목을 만들지 않는다). */
export type WebnovelsView = WebnovelListSort | "owned";

/** 주소가 고른 칩과 노벨 정책 스위치(가격 응답의 `novelPublicPolicyV2Enabled`)로 실제로 그릴 칩과 칩 목록을 정한다.
 *
 * 소장 칩은 스위치가 켜졌을 때만 있다 — 판매를 멈춘 노벨(목록에서 빠져 소장자가 찾아 들어올 길이 필요한 것)은 그때만
 * 생기고, 꺼져 있을 때(또는 그 값이 없는 옛 서버) 화면은 지금과 같아야 한다. 그래서 꺼져 있으면 `?sort=owned` 주소도
 * 최신순을 그린다. 가격 응답을 받는 중이면(`undefined`) 주소를 믿되 칩은 아직 그리지 않는다 — 받은 뒤 꺼져 있으면
 * 최신순으로 바뀐다. 칩 줄의 접근 이름도 소장 칩이 있을 때만 "목록"이고(정렬이 아닌 칩이 섞인다) 없으면 지금처럼
 * "정렬"이다. */
export function toWebnovelsView(
  requested: WebnovelsView,
  pricing: { novelPublicPolicyV2Enabled?: boolean } | undefined,
): { shown: WebnovelsView; chips: readonly WebnovelsView[]; chipsLabel: string } {
  const isOwnedOn = pricing?.novelPublicPolicyV2Enabled === true;
  const shown = requested === "owned" && pricing !== undefined && !isOwnedOn ? "latest" : requested;
  return isOwnedOn
    ? { shown, chips: ["latest", "popular", "owned"], chipsLabel: "목록" }
    : { shown, chips: ["latest", "popular"], chipsLabel: "정렬" };
}
