/** clover-page-goal-prompt.md CE-13 — 미션 3상태 투영.
 *
 * BE(`GET /me/clover/missions`)는 `achieved`·`claimed`를 매 조회마다 EXISTS로 다시 계산해
 * 돌려준다(저장된 상태가 아니다) — 이 함수는 그 두 불리언을 화면이 가를 3상태로 접는다.
 *
 * `claimed`가 `achieved`보다 우선한다 — 청구 이후 달성 신호가 사라질 수 있어도(예: `first_message`
 * 청구 뒤 메시지를 전부 지우면 그 시점의 `achieved`는 다시 거짓이 된다, clover-page-goal-prompt.md
 * T-13) 원장에 청구 기록이 남아 있는 한 "받기" 버튼을 다시 보여주면 안 된다. */
export type CloverMissionState = "unachieved" | "claimable" | "claimed";

export function projectCloverMissionState({
  achieved,
  claimed,
}: {
  achieved: boolean;
  claimed: boolean;
}): CloverMissionState {
  if (claimed) return "claimed";
  if (achieved) return "claimable";
  return "unachieved";
}
