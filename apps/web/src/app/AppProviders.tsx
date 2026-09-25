import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Provider as JotaiProvider } from "jotai";
import type { ReactNode } from "react";

import { isLegalReconsentRequiredError } from "@/entities/legal";
import { resetSessionIfLost, sessionKeys } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

/** `new QueryClient()`로 바로 만들지 않고 팩토리로 둔 건 전역 처리를 실제 `QueryClient`로 테스트하기
 * 위해서다(`AppProviders.test.ts`). 앱은 아래 `queryClient` 하나만 쓴다. */
export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    // 세션을 잃은 탭이 로그인된 척하지 않도록 쿼리·뮤테이션 어느 쪽의
    // 실패든 세션 소실 401/정지 403이면 세션을 비운다. 무한 반복 가드는 `resetSessionIfLost`에 있다.
    queryCache: new QueryCache({
      onError: (error) => resetSessionIfLost(client, error),
    }),
    /** 쓰기 21곳 각각에 onError를 다는 대신 전역
     * MutationCache 하나로 403 LEGAL_RECONSENT_REQUIRED를 잡는다. 세션을 다시 조회하면
     * `widgets/reconsent-legal`의 ReconsentModal이 `GET /me`의 재동의 플래그로 다시 뜬다
     * (staleTime: Infinity지만 활성 구독자가 있으면 invalidate로 즉시 refetch된다). */
    mutationCache: new MutationCache({
      onError: (error) => {
        if (isLegalReconsentRequiredError(error)) {
          void client.invalidateQueries({ queryKey: sessionKeys.current() });
        }
        resetSessionIfLost(client, error);
      },
    }),
    defaultOptions: {
      queries: {
        // 기본 3회 재시도는 4xx엔 무의미하고, 세션 소실 401이면 세션
        // 리셋을 3번의 백오프만큼 늦춘다. 네트워크 실패(0)·5xx만 재시도한다(entities 쿼리 선례와 같은 형태).
        // 개별 `retry`를 둔 쿼리는 그 값이 이긴다.
        retry: (failureCount, error) =>
          isApiError(error) && (error.status === 0 || error.status >= 500) && failureCount < 3,
      },
    },
  });
  return client;
}

export const queryClient = createQueryClient();

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <JotaiProvider>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </JotaiProvider>
  );
}
