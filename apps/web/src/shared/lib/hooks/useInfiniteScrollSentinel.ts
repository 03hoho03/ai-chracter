import { useEffect, useRef } from "react";

/** techspec-home-discovery.md §1 — 스크롤이 리스트 바닥에 가까워지면 `onIntersect`를 호출한다.
 * 반환된 ref를 리스트 맨 끝의 sentinel 엘리먼트에 건다. */
export function useInfiniteScrollSentinel(onIntersect: () => void, enabled: boolean) {
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled) return;
    const node = sentinelRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) onIntersect();
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [onIntersect, enabled]);

  return sentinelRef;
}
