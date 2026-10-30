/**
 * 측정 서버 런 자원의 캐시 키. 런 목록과 런 상세가 함께 쓴다 — 상세에서 턴 기록을 내보내면 목록 한 줄(원가·턴 기록 유무)도
 * 바뀌어, 두 화면이 같은 키 모양을 알아야 내보낸 뒤 둘 다 무효로 만들 수 있다.
 *
 * 런 하나에 딸린 키(상세·턴·지표)는 모두 `run(runId)` 아래에 두어, 그 런을 한 번에 무효로 만든다.
 */
export const runKeys = {
  all: ["runs"] as const,
  list: () => [...runKeys.all, "list"] as const,
  run: (runId: string) => [...runKeys.all, "run", runId] as const,
  detail: (runId: string) => [...runKeys.run(runId), "detail"] as const,
  turn: (runId: string, turn: number) => [...runKeys.run(runId), "turn", turn] as const,
  metrics: (runId: string) => [...runKeys.run(runId), "metrics"] as const,
};
