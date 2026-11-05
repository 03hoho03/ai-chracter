/** 잊게 하기 확인 대화가 돌려주는 것. `forgotten`이면 목록이 그 행 없이 다시 받아진 뒤이고, `linkedEpisodeCount`는 사실과
 * 함께 지운 장면 수다(장면 잊기는 0). `notice`는 잊지 못하고 닫혔지만 목록 위에 남길 말이 있는 경우다(그 기억이 이미
 * 없었다). 취소·닫기는 `cancelled`. */
export type ForgetOutcome =
  | { kind: "forgotten"; linkedEpisodeCount: number }
  | { kind: "notice"; message: string }
  | { kind: "cancelled" };

/** 목록 위에 남기는 잊게 하기 결과. `forgotten`은 요약 편집으로 잇는다 — 장면·사실을 지워도 요약에 같은 내용이 남을 수
 * 있고, 요약은 사용자가 직접 고칠 수 있다. */
export type MemoryListNotice =
  | { kind: "forgotten"; label: string; linkedEpisodeCount: number }
  | { kind: "message"; message: string };
