import type { QueryClient } from "@tanstack/react-query";

import type { AdminLlmCredential, AdminLlmCredentialListResponse } from "../model/credential";
import { classifyCredentialFailure, failureReloadsList } from "../model/failure";
import { withCredential, withoutCredential } from "../model/status";
import { llmCredentialKeys } from "./keys";

/** 목록과 서버 스위치를 함께 다시 받는다. */
export function invalidateCredentials(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: llmCredentialKeys.all });
}

/** 항목 응답 하나를 목록 캐시에 끼운다 — 바로 보이고, 다른 항목의 파생 상태(첫 후보)는 같은 목록에서 다시 계산된다. */
export function replaceCredential(queryClient: QueryClient, credential: AdminLlmCredential) {
  queryClient.setQueryData<AdminLlmCredentialListResponse>(llmCredentialKeys.list(), (prev) =>
    prev === undefined ? prev : { ...prev, credentials: withCredential(prev.credentials, credential) },
  );
}

/** 지운 항목을 목록 캐시에서 뺀다. 목록 자체는 여전히 맞는 캐시라 버리지 않는다. */
export function dropCredential(queryClient: QueryClient, id: string) {
  queryClient.setQueryData<AdminLlmCredentialListResponse>(llmCredentialKeys.list(), (prev) =>
    prev === undefined ? prev : { ...prev, credentials: withoutCredential(prev.credentials, id) },
  );
}

/**
 * 목록 전체 응답(순서·목록 사용)을 캐시에 넣는다. 그 순간 목록 재조회가 날아가고 있으면 늦게 도착한 옛 목록이 방금 넣은 새 목록을
 * 덮으므로 먼저 취소한다. 취소는 기본으로 그 조회가 시작될 때의 캐시로 되돌리므로, 끝까지 기다린 뒤 넣어야 되돌림이 넣은 값을 지우지
 * 않는다.
 *
 * 취소한 재조회는 다른 뮤테이션이 이 응답보다 뒤의 변경을 줍겠다고 건 것일 수 있다 — 확인 호출이 기다리는 동안 순서 저장이 응답에 담을
 * 목록을 읽고, 그 뒤 확인이 커밋돼 그 응답이 먼저 도착해 재조회를 걸었으면, 늦게 온 순서 응답은 확인 전의 목록이다. 그래서 날아가던
 * 재조회가 있었을 때만 넣은 뒤 다시 건다. 늘 다시 걸면 재조회 동안 위·아래가 잠겨 연속 이동마다 버튼이 잠긴다.
 */
export async function putList(queryClient: QueryClient, list: AdminLlmCredentialListResponse) {
  const queryKey = llmCredentialKeys.list();
  const wasFetching = queryClient.isFetching({ queryKey }) > 0;
  await queryClient.cancelQueries({ queryKey });
  queryClient.setQueryData(queryKey, list);
  if (wasFetching) void queryClient.invalidateQueries({ queryKey });
}

/** 화면이 본 목록이 틀렸다는 뜻의 실패(낡은 판·낡은 켜기 막힘·없는 항목·겹친 변경·사라진 저장소 설정)면 다시 받는다. */
export function reloadIfListStale(queryClient: QueryClient, error: unknown) {
  if (failureReloadsList(classifyCredentialFailure(error))) void invalidateCredentials(queryClient);
}
