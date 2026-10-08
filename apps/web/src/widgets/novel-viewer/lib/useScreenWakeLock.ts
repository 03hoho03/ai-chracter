import { useEffect } from "react";

/** 이 브라우저가 화면 꺼짐 방지(Screen Wake Lock)를 지원하는가. 지원하지 않으면 보기 설정에서 그 줄을 숨긴다. */
export function isScreenWakeLockSupported(): boolean {
  return typeof navigator !== "undefined" && "wakeLock" in navigator;
}

/**
 * 켜져 있는 동안 화면이 꺼지지 않게 잡아 둔다. 브라우저는 탭이 숨으면 잡아 둔 것을 스스로 놓으므로, 다시 보이면 새로
 * 요청한다. 끄거나 읽기 화면을 떠나면 놓는다.
 *
 * 요청은 배터리 절약 모드·권한 정책 등으로 거절될 수 있는데, 그때 화면은 평소처럼 꺼질 뿐 읽기에는 지장이 없어 알리지
 * 않고 넘어간다.
 */
export function useScreenWakeLock(enabled: boolean) {
  useEffect(() => {
    if (!enabled || !isScreenWakeLockSupported()) return;
    let sentinel: WakeLockSentinel | undefined;
    let isRequesting = false;
    let isActive = true;

    async function request() {
      if (isRequesting || document.visibilityState !== "visible") return;
      if (sentinel !== undefined && !sentinel.released) return;
      isRequesting = true;
      try {
        const acquired = await navigator.wakeLock.request("screen");
        // 기다리는 사이 끄거나 떠났으면 받자마자 놓는다.
        if (isActive) sentinel = acquired;
        else void acquired.release().catch(() => undefined);
      } catch {
        // 거절돼도 화면이 평소처럼 꺼질 뿐이다(위 설명).
      } finally {
        isRequesting = false;
      }
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") void request();
    }

    void request();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      isActive = false;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      void sentinel?.release().catch(() => undefined);
    };
  }, [enabled]);
}
