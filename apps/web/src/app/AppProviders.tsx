import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Provider as JotaiProvider } from "jotai";
import type { ReactNode } from "react";

import { isLegalReconsentRequiredError } from "@/entities/legal";
import { sessionKeys } from "@/entities/session";

/** consent-gate-goal-prompt.md CG-12 — 쓰기 21곳 각각에 onError를 다는 대신 전역
 * MutationCache 하나로 403 LEGAL_RECONSENT_REQUIRED를 잡는다. 세션을 다시 조회하면
 * `widgets/reconsent-legal`의 ReconsentModal이 `GET /me`의 재동의 플래그로 다시 뜬다
 * (staleTime: Infinity지만 활성 구독자가 있으면 invalidate로 즉시 refetch된다). */
export const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (error) => {
      if (isLegalReconsentRequiredError(error)) {
        void queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
      }
    },
  }),
});

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <JotaiProvider>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </JotaiProvider>
  );
}
