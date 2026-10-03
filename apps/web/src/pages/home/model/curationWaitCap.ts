import { useEffect, useRef, useState } from "react";

/** 목록이 이미 준비됐는데 큐레이션 응답만 기다리며 그리드를 붙잡아 두는 시간의 상한.
 *
 * 1초를 넘는 응답 지연부터 사용자가 흐름이 끊겼다고 느낀다(Nielsen 의 응답 시간 한계). 큐레이션은 1행 조회라
 * 정상이라면 목록보다 먼저 오므로, 목록이 다 온 뒤 1초를 넘겨 더 기다린다면 그건 이상 상황이다 — 그 경계에 네트워크
 * 흔들림 여유 0.5초를 더한 값까지만 기다리고, 넘기면 섹션을 포기하고 그리드를 먼저 그린다. */
export const CURATION_WAIT_LIMIT_MS = 1_500;

/** "그리드를 붙잡고 있는가" 를 렌더마다 받아, 붙잡은 상태가 상한만큼 이어지면 한 번 포기를 알린다.
 * 붙잡기가 상한 전에 풀리면(응답 도착·필터 걸림) 예약을 지우고, 다시 붙잡으면 새로 잰다. 한 번 포기하면 그 뒤로는
 * 다시 예약하지 않는다 — 포기한 화면에 늦게 온 큐레이션을 끼워 넣으면 이미 그린 그리드가 밀려 내려간다. */
export function createCurationWaitCap(onGiveUp: () => void, limitMs: number = CURATION_WAIT_LIMIT_MS) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let hasGivenUp = false;

  const cancel = () => {
    if (timer === undefined) return;
    clearTimeout(timer);
    timer = undefined;
  };

  return {
    update(isHoldingGrid: boolean) {
      if (!isHoldingGrid || hasGivenUp) {
        cancel();
        return;
      }
      if (timer !== undefined) return;
      timer = setTimeout(() => {
        timer = undefined;
        hasGivenUp = true;
        onGiveUp();
      }, limitMs);
    },
    dispose: cancel,
  };
}

/** `createCurationWaitCap` 을 화면 한 번의 마운트에 묶는다. 돌려주는 값이 참이면 이 마운트에서는 큐레이션을 그리지
 * 않는다(늦게 와도). */
export function useCurationWaitCap(isHoldingGrid: boolean): boolean {
  const [hasGivenUp, setHasGivenUp] = useState(false);
  const capRef = useRef<ReturnType<typeof createCurationWaitCap> | null>(null);

  useEffect(() => {
    const cap = createCurationWaitCap(() => setHasGivenUp(true));
    capRef.current = cap;
    return () => {
      cap.dispose();
      capRef.current = null;
    };
  }, []);

  useEffect(() => {
    capRef.current?.update(isHoldingGrid);
  }, [isHoldingGrid]);

  return hasGivenUp;
}
