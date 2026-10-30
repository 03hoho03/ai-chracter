import { useQuery } from "@tanstack/react-query";

import { getRuns } from "@/shared/api/client";

import { runKeys } from "./runKeys";

/**
 * 런 목록. 측정 서버는 같은 컴퓨터의 로컬 프로세스라 기본값 둘을 바꾼다.
 * - 다시 시도하지 않는다 — 실패는 대개 "꺼져 있음"이고, 기본 재시도(세 번, 1·2·4초)를 기다리는 동안 띄우는 방법을 늦게 보일 뿐이다.
 * - 브라우저가 오프라인이라고 여겨도 요청한다 — 기본값은 그때 요청을 멈추는데, 와이파이가 꺼져도 127.0.0.1 은 닿는다.
 */
export function useRuns() {
  return useQuery({
    queryKey: runKeys.list(),
    queryFn: () => getRuns(),
    retry: false,
    networkMode: "always",
  });
}
