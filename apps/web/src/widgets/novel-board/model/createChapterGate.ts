import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";

/** 상단바 "다음 화 만들기"를 지금 못 누르는가. 화 작업·AI 수정이 돌거나 준비 중이면(`isBusy`), 원래 대화방이 지워졌으면 못 누른다.
 * 구성 흐름 스위치를 실은 가격 응답을 아직 받는 중일 때도 막는다 — 그 순간 누르면 스위치가 켜져 있어도 옛 흐름(경계 고르기)이
 * 시작된다. */
export function isCreateChapterBlocked(
  flow: Pick<NovelChapterJobFlow, "isBusy" | "isRoomGone">,
  options: { isSwitchPending: boolean },
): boolean {
  return flow.isBusy || flow.isRoomGone || options.isSwitchPending;
}
