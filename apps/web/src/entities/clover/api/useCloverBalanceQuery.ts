import { useQuery } from "@tanstack/react-query";

import { cloverBalanceQueryOptions } from "./cloverBalanceQueryOptions";

export type { CloverBalanceResponse } from "./cloverBalanceQueryOptions";

/** 훅은 `queryOptions`를 감싸기만 한다 — `entities/session`의 `useSessionQuery`와 같은 형태.
 * 옵션을 따로 두는 이유는 라우터 가드(`ensureQueryData`)가 같은 옵션을 공유해야 하기 때문이다.
 *
 * `enabled` 는 로그인 없이 열리는 화면(클로버 충전)이 비로그인에게 잔액을 묻지 않게 끄는 자리다 — 물으면 401 이다. */
export function useCloverBalanceQuery({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ ...cloverBalanceQueryOptions, enabled });
}
