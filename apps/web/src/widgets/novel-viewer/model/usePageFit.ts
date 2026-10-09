import { useLayoutEffect, useRef, useState } from "react";

import { isSamePageFit, toPageFit, type PageFit } from "../lib/pageFit";

/**
 * 창에 판형을 맞춘 배치(`toPageFit`). 창 크기·회전·safe-area 가 바뀌면 다시 구한다.
 *
 * 창 크기와 safe-area 는 `probeRef` 를 단 요소 하나로 읽는다 — 뷰포트를 덮는 고정 요소에 `env()` safe-area 를 패딩으로
 * 줘 두면, 그 요소의 크기가 창 크기이고 계산된 패딩이 safe-area 다(스크립트로 `env()` 를 바로 읽을 길이 없다). 그
 * 요소의 크기 변화를 지켜보므로 창 크기 변화도 함께 잡는다. 칠하기 전에 처음 구해 판형이 한 번 다른 자리에 그려지지
 * 않게 한다 — 구하기 전(`undefined`)에는 본문을 그리지 않는다.
 */
export function usePageFit(isFinePointer: boolean) {
  const probeRef = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<PageFit | undefined>(undefined);

  useLayoutEffect(() => {
    const probe = probeRef.current;
    if (!probe) return;
    const target = probe;

    function update() {
      const style = getComputedStyle(target);
      const next = toPageFit({
        viewportWidth: target.clientWidth,
        viewportHeight: target.clientHeight,
        safeArea: {
          top: pxOf(style.paddingTop),
          right: pxOf(style.paddingRight),
          bottom: pxOf(style.paddingBottom),
          left: pxOf(style.paddingLeft),
        },
        isFinePointer,
      });
      setFit((current) => (isSamePageFit(current, next) ? current : next));
    }

    update();
    const observer = new ResizeObserver(update);
    observer.observe(target);
    return () => observer.disconnect();
  }, [isFinePointer]);

  return { fit, probeRef };
}

function pxOf(value: string): number {
  return Number.parseFloat(value) || 0;
}
