import { useCallback, useState } from "react";

/**
 * 가로 스크롤 컨테이너의 오른쪽이 더 잘려 있는지 추적한다. `packages/ui/CLAUDE.md`의
 * `data-clipped-below`(드롭다운 메뉴 하단 페이드)와 같은 이유다 — macOS·iOS 오버레이 스크롤바는
 * 상시 표시가 없어 **잘렸다는 신호가 하나도 없다**. 스텝 탭 스트립(builder-goal-prompt.md §1-5,
 * "스텝 탭은 가로 스크롤이 된다")이 첫 소비처다.
 *
 * 콜백 ref인 이유는 두 Shell 모두 컨테이너가 마운트 시점에 항상 존재해 `useEffect`로도 되지만,
 * `useFocusFirstError.ts`와 같은 관례(콜백 ref + `ResizeObserver`)를 맞춘 것이다. 폭이 바뀌는 계기가
 * 리사이즈뿐 아니라 **탭 라벨 자체가 늘어나는 경우**(발행 실패로 경고 아이콘이 붙어 탭 스트립 전체
 * 너비가 커진다)도 있어 `scroll` 리스너만으로는 못 잡는다.
 */
export function useHorizontalScrollClip() {
  const [isClippedRight, setIsClippedRight] = useState(false);

  const ref = useCallback((el: HTMLDivElement | null) => {
    if (!el) return;

    const update = () => setIsClippedRight(el.scrollWidth - el.scrollLeft - el.clientWidth > 1);
    update();

    const observer = new ResizeObserver(update);
    observer.observe(el);
    el.addEventListener("scroll", update);
    return () => {
      observer.disconnect();
      el.removeEventListener("scroll", update);
    };
  }, []);

  return { ref, isClippedRight };
}
