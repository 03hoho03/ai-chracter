import { onlineManager } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

function subscribeOnline(listener: () => void) {
  return onlineManager.subscribe(listener);
}

/** TanStack 의 `onlineManager` 판단을 그대로 따른다 — 그 판단으로 저장 요청이 멈추고 연결이 돌아오면 다시 나가므로, 같은 판단을
 * 보여야 화면이 실제 저장과 어긋나지 않는다. */
export function useIsOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, () => onlineManager.isOnline(), () => true);
}
