/**
 * 빌더 저장 상태. 화면에는 임시저장 버튼의 아이콘과 접근 이름으로만 보인다.
 *
 * - `idle`: 이 화면에서 아직 저장한 적이 없다.
 * - `pending`: 편집이 있어 자동저장을 기다리는 중이다(입력을 멈추면 곧 저장된다).
 * - `saving`: 저장 요청이 나가 있다. 오프라인이면 요청이 멈춰 이 상태로 남는다 — 연결을 알리는 건 그리는 쪽 몫이다.
 * - `saved` / `failed`: 마지막으로 끝난 저장의 결과.
 */
export type AutosaveStatus = "idle" | "pending" | "saving" | "saved" | "failed";

/**
 * 지금 창을 닫으면 편집이 사라질 수 있는가 — 새로고침·탭 닫기 때 브라우저 확인창을 띄울지의 판정.
 *
 * 저장을 기다리는 편집(`pending`), 끝나지 않은 저장(`saving`), 실패한 저장(`failed`)이 그렇다. 실패는 자동저장 실패 알림이
 * "입력한 내용은 그대로 있다"고 약속한 상태라, 그대로 닫으면 그 내용이 경고 없이 사라진다. 저장이 끝났거나(`saved`) 아직
 * 편집이 없으면(`idle`) 묻지 않는다. 이미지 업로드는 이 저장소가 세지 않아 판정 밖이다.
 */
export function hasUnsavedChanges(status: AutosaveStatus): boolean {
  return status === "pending" || status === "saving" || status === "failed";
}

export type AutosaveStatusStore = {
  getSnapshot: () => AutosaveStatus;
  subscribe: (listener: () => void) => () => void;
  /** 자동저장이 예약됐다(디바운스 대기). 저장이 이미 나가 있으면 그 상태를 덮지 않는다. */
  markPending: () => void;
  /** 저장 하나를 감싼다. 결과는 그대로 돌려주고 실패도 그대로 던진다. */
  track: <T>(save: () => Promise<T>) => Promise<T>;
};

/**
 * 저장 상태를 담는 외부 저장소. React 상태가 아닌 이유는 셸을 다시 그리지 않기 위해서다 — 저장은 입력을 멈출 때마다 돌고, 셸이
 * 그 상태를 쥐면 셸과 미리보기가 그때마다 다시 그려진다. 상태를 보이는 버튼 하나만 `useSyncExternalStore` 로 구독한다.
 *
 * 저장 요청은 초안 하나에 한 줄로 서서 차례로 끝나지만, 앞 요청이 끝나기 전에 다음 요청이 시작될 수는 있다. 그래서 나가 있는 요청
 * 수를 세고 그 수가 0이 될 때 마지막 결과를 보인다 — 앞 요청의 성공이 뒤 요청이 도는 중에 "저장됨"을 띄우지 않는다.
 */
export function createAutosaveStatusStore({
  onSaved,
}: {
  /** 저장 하나가 성공할 때마다 부른다. 어느 경로의 저장이든 성공하면 "마지막 편집이 서버에 없다"는 실패 알림이 거짓이 되므로, 그 알림을
   * 걷는 자리를 저장 상태와 같은 곳에 둔다. */
  onSaved?: () => void;
} = {}): AutosaveStatusStore {
  let inFlight = 0;
  let isPending = false;
  let lastResult: AutosaveStatus = "idle";
  let snapshot: AutosaveStatus = "idle";
  const listeners = new Set<() => void>();

  function publish() {
    let next: AutosaveStatus = lastResult;
    if (isPending) next = "pending";
    if (inFlight > 0) next = "saving";
    if (next === snapshot) return;
    snapshot = next;
    for (const listener of listeners) listener();
  }

  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    markPending: () => {
      isPending = true;
      publish();
    },
    track: async (save) => {
      // 저장이 시작되면 기다리던 편집은 그 저장에 실린다(자동저장·임시저장·발행 직전 저장 모두 지금 폼 값 전체를 보낸다).
      isPending = false;
      inFlight += 1;
      publish();
      try {
        const result = await save();
        lastResult = "saved";
        onSaved?.();
        return result;
      } catch (error) {
        lastResult = "failed";
        throw error;
      } finally {
        inFlight -= 1;
        publish();
      }
    },
  };
}
