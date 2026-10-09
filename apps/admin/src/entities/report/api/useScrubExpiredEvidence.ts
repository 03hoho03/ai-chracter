import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect } from "react";

/**
 * 신고 시점 사본은 보유 기한이 지나면 보여서는 안 된다. 상세를 연 채 기한을 넘기면 그때 활성 캐시의 응답을 `redact` 로
 * 바꾼다 — 기한 시각 타이머와, 탭으로 돌아온 순간(타이머가 밀렸을 수 있다) 둘 다에서. 외부 시계와의 동기화라 효과로 한다.
 * `queryKey`·`redact` 는 렌더마다 같은 값이어야 한다(키는 `useMemo`, 함수는 모듈 수준) — 아니면 타이머가 매번 다시 걸린다.
 */
export function useScrubExpiredEvidence<T>(queryKey: QueryKey, expiresAt: string | undefined, redact: (data: T) => T) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!expiresAt) return;
    const scrub = () => {
      queryClient.setQueryData<T>(queryKey, (data) => (data === undefined ? data : redact(data)));
    };
    let timer: number;
    const schedule = () => {
      const remaining = Date.parse(expiresAt) - Date.now();
      if (remaining <= 0) {
        scrub();
        return;
      }
      timer = window.setTimeout(schedule, Math.min(remaining, 2_147_483_647));
    };
    schedule();
    document.addEventListener("visibilitychange", scrub);
    window.addEventListener("focus", scrub);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", scrub);
      window.removeEventListener("focus", scrub);
    };
  }, [expiresAt, queryClient, queryKey, redact]);
}
