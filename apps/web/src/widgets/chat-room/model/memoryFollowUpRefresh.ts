/** 스트림이 끝난 뒤 기억을 한 번 더 받기까지 기다리는 시간. 서버는 응답 본문을 다 보낸 **뒤에** 요약 접기를
 * 백그라운드로 시작하므로, 스트림 종료 직후의 리페치는 접기 이전 값을 받는다. 이 값은 요약 호출 한 번의
 * 지연을 덮을 만큼이어야 하는데 아직 실측이 없다 — 실측 뒤 여기 한 곳만 고친다. */
export const MEMORY_FOLLOW_UP_REFRESH_DELAY_MS = 5_000;

export type MemoryFollowUpState = {
  roomId: string;
  isSending: boolean;
  isPanelOpen: boolean;
};

export type MemoryFollowUpRefresher = {
  /** 렌더마다 지금 상태를 넘긴다. 전송이 끝난 순간 패널이 열려 있으면 지연 리페치를 한 번 예약하고, 패널이
   * 닫히거나 방이 바뀌면 예약을 버린다. */
  update: (state: MemoryFollowUpState) => void;
  dispose: () => void;
};

/** 열린 기억 패널이 접기 결과를 한 턴 늦게 보는 것을 막는 지연 리페치. 닫힌 패널은 열 때 다시 받으므로
 * 예약하지 않는다(요청을 늘리지 않는다). */
export function createMemoryFollowUpRefresher(
  refresh: (roomId: string) => void,
  delayMs: number = MEMORY_FOLLOW_UP_REFRESH_DELAY_MS,
): MemoryFollowUpRefresher {
  let previous: MemoryFollowUpState | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function cancel() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  return {
    update(state) {
      if (previous !== null && previous.roomId !== state.roomId) {
        cancel();
        previous = state;
        return;
      }
      if (!state.isPanelOpen) cancel();
      const hasSendingEnded = previous?.isSending === true && !state.isSending;
      previous = state;
      if (!hasSendingEnded || !state.isPanelOpen) return;
      cancel();
      const { roomId } = state;
      timer = setTimeout(() => {
        timer = null;
        refresh(roomId);
      }, delayMs);
    },
    dispose: cancel,
  };
}
