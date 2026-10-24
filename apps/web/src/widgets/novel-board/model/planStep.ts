/** 구성 모드 단계 줄의 현재 단계(0 담을 대화, 1 전체 구성안, 2 화별 장면·원고). 앞 단계를 승인해야 다음 단계가 이어진다 — 담을
 * 대화에 승인하지 않은 판(저장 전 제안·초안)이 있으면 그 단계가 먼저다. 방이 지워진 소설은 담을 대화를 읽지 않아(`undefined`) 구성안
 * 상태로 정한다. */
export function toCurrentPlanStep(status: {
  selection: "unsaved" | "draft" | "approved" | undefined;
  outline: "draft" | "approved" | undefined;
}): 0 | 1 | 2 {
  if (status.selection === "unsaved" || status.selection === "draft") return 0;
  if (status.selection === undefined && status.outline === undefined) return 0;
  return status.outline === "approved" ? 2 : 1;
}
