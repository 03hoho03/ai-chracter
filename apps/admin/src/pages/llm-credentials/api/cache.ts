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
 * 목록 전체 응답(순서·목록 사용)을 캐시에 넣는다. 그 순간 창 포커스 재조회가 날아가고 있으면 늦게 도착한 옛 목록이 방금 넣은 새
 * 목록을 덮으므로 먼저 취소한다. 취소는 기본으로 그 조회가 시작될 때의 캐시로 되돌리므로, 끝까지 기다린 뒤 넣어야 되돌림이 넣은
 * 값을 지우지 않는다.
 */
export async function putList(queryClient: QueryClient, list: AdminLlmCredentialListResponse) {
  await queryClient.cancelQueries({ queryKey: llmCredentialKeys.list() });
  queryClient.setQueryData(llmCredentialKeys.list(), list);
}

/** 화면이 본 목록이 틀렸다는 뜻의 실패(낡은 판·낡은 켜기 막힘·없는 항목·겹친 변경·사라진 저장소 설정)면 다시 받는다. */
export function reloadIfListStale(queryClient: QueryClient, error: unknown) {
  if (failureReloadsList(classifyCredentialFailure(error))) void invalidateCredentials(queryClient);
}
