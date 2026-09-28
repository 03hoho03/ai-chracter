import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMemoryFollowUpRefresher } from "./memoryFollowUpRefresh";

const DELAY = 1_000;

function setup() {
  const refresh = vi.fn<(roomId: string) => void>();
  const refresher = createMemoryFollowUpRefresher(refresh, DELAY);
  return { refresh, refresher };
}

describe("createMemoryFollowUpRefresher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  // 서버는 응답을 다 보낸 뒤에 요약을 접는다 — 열린 패널은 스트림 종료 직후 리페치로는 접기 결과를 못 본다.
  it("refreshes the room once, after the delay, when a send ends with the panel open", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });

    vi.advanceTimersByTime(DELAY - 1);
    expect(refresh).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledWith("a");

    // 다음 렌더가 같은 상태를 다시 넘겨도 또 예약하지 않는다.
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    vi.advanceTimersByTime(DELAY * 3);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not schedule anything when the panel is closed as the send ends", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: false });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: false });
    vi.advanceTimersByTime(DELAY * 3);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("does not schedule when nothing was being sent", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    vi.advanceTimersByTime(DELAY * 3);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("drops the pending refresh when the panel is closed before the delay", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: false });
    vi.advanceTimersByTime(DELAY * 3);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("drops the pending refresh when the room changes before the delay", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    refresher.update({ roomId: "b", isSending: false, isPanelOpen: true });
    vi.advanceTimersByTime(DELAY * 3);
    expect(refresh).not.toHaveBeenCalled();
  });

  // 방이 바뀌는 렌더에서 "보내는 중 → 아님"이 보여도 그건 이전 방의 전송이다.
  it("does not treat a room switch as the end of a send in the new room", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: true });
    refresher.update({ roomId: "b", isSending: false, isPanelOpen: true });
    vi.advanceTimersByTime(DELAY * 3);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("drops the pending refresh on dispose (unmount)", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    refresher.dispose();
    vi.advanceTimersByTime(DELAY * 3);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("restarts the wait when another send ends before the delay, refreshing once", () => {
    const { refresh, refresher } = setup();
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    vi.advanceTimersByTime(DELAY / 2);
    refresher.update({ roomId: "a", isSending: true, isPanelOpen: true });
    refresher.update({ roomId: "a", isSending: false, isPanelOpen: true });
    vi.advanceTimersByTime(DELAY - 1);
    expect(refresh).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
