import type { QueryClient } from "@tanstack/react-query";

import { sessionKeys } from "../api/keys";
import { isSessionLostError } from "../model/sessionLost";
import { isSuspendedError } from "../model/suspendedAccount";

/** backlog-l-goal-prompt.md BL-6 — 어떤 요청이 세션 소실 401이나 정지 403으로 실패하면 캐시된 세션을
 * 비워 헤더가 비로그인으로 돌아오게 한다. `app/AppProviders.tsx`의 QueryCache·MutationCache와 fetch 기반
 * SSE 훅(전송·미리보기) catch, 모두 네 곳이 이 함수 하나를 부른다 — 판정·가드를 복사하지 않는다.
 *
 * 자동 이동은 하지 않는다(입력값 보존). 다음 인증 라우트 진입에서 `requireSession`이 로그인으로 보낸다.
 *
 * 🔴 **세션 데이터가 있을 때만 리셋한다.** 세션 쿼리 자신도 401로 throw하므로(`sessionQueryOptions`),
 * 가드가 없으면 리셋 → 활성 구독자 리페치 → 401 → QueryCache.onError → 리셋 … 이 끝없이 돈다. 리셋은
 * data를 undefined로 되돌리므로 두 번째 401에서는 가드가 막는다(리페치 실패는 옛 data를 남기므로 포커스
 * 리페치의 첫 401은 가드를 통과한다 — 그게 이 리셋이 필요한 경우다). 로그인 화면처럼 처음부터 세션이
 * 없으면 리셋할 것도 없다. */
export function resetSessionIfLost(queryClient: QueryClient, error: unknown): void {
  if (!isSessionLostError(error) && !isSuspendedError(error)) return;
  if (queryClient.getQueryData(sessionKeys.current()) === undefined) return;
  // 로그아웃과 같은 이유로 resetQueries다(`features/logout/api/useLogoutMutation.ts`).
  void queryClient.resetQueries({ queryKey: sessionKeys.current() });
}
