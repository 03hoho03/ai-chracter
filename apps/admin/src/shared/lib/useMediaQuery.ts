import { useCallback, useSyncExternalStore } from "react";

/** SSR 이 없는 SPA 라 첫 렌더부터 실제 값을 읽는다(넓은 화면에서 좁은 화면 분기가 한 번 깜빡이지 않는다). */
export function useMediaQuery(query: string) {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mediaQueryList = window.matchMedia(query);
      mediaQueryList.addEventListener("change", onChange);
      return () => mediaQueryList.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches);
}

/**
 * 셸의 사이드바·상단바 경계(CSS `lg:`, 64rem)와 같은 값이다. 셸 자체는 CSS 로만 가르고, body 로 포털돼
 * 부모 클래스가 닿지 않는 것(드로어 같은 시트)만 이 훅으로 가른다.
 */
export function useIsDesktopLayout() {
  return useMediaQuery("(min-width: 64rem)");
}
