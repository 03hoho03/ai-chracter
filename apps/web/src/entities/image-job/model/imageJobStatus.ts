import type { components } from "@ai-character-chat/api-types";
import type { QueryStatus } from "@tanstack/react-query";

export type ImageJobStatus = components["schemas"]["ImageGenerationJobStatus"];

const POLL_INTERVAL_MS = 1500;

/** 서버가 더 바꾸지 않는 상태인가. 첫 응답 전(`undefined`)은 아직 진행 중으로 본다. */
export function isTerminalImageJobStatus(status: ImageJobStatus | undefined): boolean {
  return status === "succeeded" || status === "failed";
}

/** 잡 폴링 간격. 터미널이면 더 물을 것이 없고, 조회가 오류 상태면(재시도까지 다 실패) 멈춘다 —
 * 인터벌은 오류를 보지 않아서, 멈추지 않으면 완료 후 TTL 이 지나 404 가 나는 잡도 1.5초마다 영원히
 * 묻는다. 오류 뒤 회복은 창 포커스·재연결 재조회가 맡는다: 오류가 쿼리를 무효로 표시해 그때 반드시
 * 다시 묻고, 그 재조회가 성공하면 `status` 가 오류를 벗어나 폴링이 다시 걸린다. */
export function getImageJobRefetchInterval(state: {
  status: QueryStatus;
  data?: { status: ImageJobStatus } | undefined;
}): number | false {
  if (state.status === "error") return false;
  return isTerminalImageJobStatus(state.data?.status) ? false : POLL_INTERVAL_MS;
}

/** 완료된 잡은 창 포커스·재연결로 다시 묻지 않는다. 서버는 마지막 기록 후 약 1시간 뒤 잡을 지우므로,
 * 그 뒤 포커스 재조회의 404 가 이미 받은 완료 결과를 오류로 덮게 된다. 진행 중이면 포커스 복귀 때
 * 바로 묻도록 0 이다. */
export function getImageJobStaleTime(data: { status: ImageJobStatus } | undefined): number {
  return isTerminalImageJobStatus(data?.status) ? Infinity : 0;
}

/** 폴링이 실패한 상태인가 — **오류가 마지막 성공보다 최근인가**로 본다.
 *
 * 쿼리의 `isError` 로 보면 깜빡인다: 응답을 한 번도 받지 못한 쿼리는 새 조회·재시도가 시작될 때마다
 * `status` 가 `pending` 으로 돌아간다. 두 시각은 조회 시작·재시도에서는 바뀌지 않고 성공
 * (`dataUpdatedAt`)과 재시도까지 다 실패한 오류(`errorUpdatedAt`)에서만 바뀌므로, 재조회 동안에는 직전
 * 판정이 유지되고 성공하면 바로 거짓으로 돌아간다. 오류가 한 번이라도 있었는지로 보면 회복을 모른다 —
 * 포커스 재조회가 진행 중 응답을 받아도 오류로 남는다. 둘 다 0 인 새 잡은 오류가 아니다. */
export function hasImageJobPollError({
  errorUpdatedAt,
  dataUpdatedAt,
}: {
  errorUpdatedAt: number;
  dataUpdatedAt: number;
}): boolean {
  return errorUpdatedAt > dataUpdatedAt;
}
