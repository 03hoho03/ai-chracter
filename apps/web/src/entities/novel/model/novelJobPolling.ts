import type { components } from "@ai-character-chat/api-types";

import { isApiError } from "@/shared/api/client";

export type NovelJobStatus = components["schemas"]["NovelJobResponse"]["status"];

/** 진행 중일 때 묻는 간격. 장 하나를 쓰는 데 분 단위가 걸리는 작업이라 이미지 작업보다 느슨하다. */
export const NOVEL_JOB_POLL_INTERVAL_MS = 2_000;

/** 조회가 실패하고 있을 때 묻는 간격. 서버가 다시 뜨는 동안처럼 잠깐 묻지 못하는 때에도 이용자는 화면을 지켜보고
 * 있으므로 멈추지 않고, 대신 실패하는 서버를 두드리지 않게 느리게 묻는다. */
export const NOVEL_JOB_ERROR_POLL_INTERVAL_MS = 10_000;

/** 서버가 더 바꾸지 않는 상태인가. 첫 응답 전(`undefined`)은 아직 진행 중으로 본다. */
export function isTerminalNovelJobStatus(status: NovelJobStatus | undefined): boolean {
  return status === "succeeded" || status === "failed";
}

/** 폴링이 실패한 상태인가 — **오류가 마지막 성공보다 최근인가**로 본다. 쿼리의 `isError` 는 응답을 한 번도 못
 * 받은 쿼리에서 재조회·재시도가 시작될 때마다 `pending` 으로 돌아가 깜빡이고, "오류가 한 번이라도 있었나"로
 * 보면 다음 성공에서 회복한 것을 모른다. 두 시각은 성공과 재시도까지 다 실패한 오류에서만 바뀐다. 둘 다 0 인
 * 새 작업은 오류가 아니다. */
export function hasNovelJobPollError({
  errorUpdatedAt,
  dataUpdatedAt,
}: {
  errorUpdatedAt: number;
  dataUpdatedAt: number;
}): boolean {
  return errorUpdatedAt > dataUpdatedAt;
}

/** 작업이 없어졌다는 404. 소설이 지워지면 그 작업도 함께 지워지고, 남의 소설·다른 소설의 작업도 서버는 같은
 * 404 로 답한다 — 몇 번을 다시 물어도 바뀌지 않는다. */
function isNovelJobGoneError(error: unknown): boolean {
  return isApiError(error) && error.status === 404;
}

/** 지켜보던 작업이 없어졌나 — 마지막 응답이 그 404 인가. 그렇다면 폴링이 멈추므로 화면은 작업을 끝난 것으로
 * 다뤄야 한다(진행 중으로 남기면 버튼이 영영 잠기고, 진행 줄은 더는 묻지 않는데 다시 확인하겠다고 말한다). 404 뒤에
 * 다시 성공했으면 없어진 것이 아니다. */
export function isNovelJobGone(state: { error: unknown; errorUpdatedAt: number; dataUpdatedAt: number }): boolean {
  return hasNovelJobPollError(state) && isNovelJobGoneError(state.error);
}

/** 작업 폴링 간격. 끝났으면 멈춘다. 조회가 실패하고 있으면 **멈추지 않고** 느린 간격으로 계속 묻는다 — 이미지
 * 작업은 오류에서 멈추고 창 포커스 복귀에 회복을 맡기지만, 장 작업은 길고 이용자가 화면을 떠나지 않고 지켜보므로
 * 포커스 복귀가 오지 않는다. 멈추면 서버가 다시 뜬 뒤에도 "확인하지 못하고 있어요"에 영원히 머문다. 예외는
 * 작업이 없어졌다는 404 하나다(다시 물어도 같은 답이다). */
export function getNovelJobRefetchInterval(state: {
  data?: { status: NovelJobStatus } | undefined;
  error: unknown;
  errorUpdatedAt: number;
  dataUpdatedAt: number;
}): number | false {
  if (isTerminalNovelJobStatus(state.data?.status)) return false;
  if (isNovelJobGone(state)) return false;
  if (hasNovelJobPollError(state)) return NOVEL_JOB_ERROR_POLL_INTERVAL_MS;
  return NOVEL_JOB_POLL_INTERVAL_MS;
}

/** 끝난 작업은 창 포커스·재연결로 다시 묻지 않는다(결과가 더 바뀌지 않는다). 진행 중이면 포커스 복귀 때 바로
 * 묻도록 0 이다. */
export function getNovelJobStaleTime(data: { status: NovelJobStatus } | undefined): number {
  return isTerminalNovelJobStatus(data?.status) ? Infinity : 0;
}
