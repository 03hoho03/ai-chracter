import { useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

function debounce<TArgs extends unknown[]>(fn: (...args: TArgs) => void, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pendingArgs: TArgs | undefined;

  const run = () => {
    timer = undefined;
    const args = pendingArgs;
    pendingArgs = undefined;
    if (args !== undefined) fn(...args);
  };

  const debounced = (...args: TArgs) => {
    pendingArgs = args;
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(run, ms);
  };
  debounced.cancel = () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    pendingArgs = undefined;
  };
  /** 대기 중인 호출을 지금 실행한다(대기 중인 게 없으면 아무 일도 하지 않는다). */
  debounced.flush = () => {
    if (timer === undefined) return;
    clearTimeout(timer);
    run();
  };
  return debounced;
}

/** 저장이 계속 실패하는 동안 디바운스마다 새 토스트가 뜨지 않도록 id를 고정한다 — id가 없으면 실패한
 * 횟수만큼 쌓이고(sonner 기본 `visibleToasts` 3), 600px 이하에서는 토스트가 전체 폭으로 바닥에 깔려
 * 입력 중인 필드를 가린다. `duration: Infinity`인 이유는 이게 "방금 일어난 일"이 아니라 **"마지막 편집이
 * 서버에 없다"는 지속 상태**이기 때문이다 — 기본 4초로 두면 사용자가 잠깐 눈을 뗀 사이 사라져, 저장되지
 * 않은 걸 모른 채 탭을 닫는다. 해제는 다음 저장 성공과 빌더 이탈 두 가지다 — 저장 성공은 어느 경로의 저장이든 `useDraftPersistence` 의 저장 상태가 걷는다. 성공 토스트는
 * 띄우지 않는다 — 1.5초마다 초록 토스트가 뜨면 재앙이다.
 *
 * 참고: 진짜 오프라인에서는 이 토스트가 뜨지 않는다. `app/AppProviders.tsx`의 `QueryClient`가 기본
 * `networkMode: "online"`이라 뮤테이션이 **pause**되고(재접속 시 한꺼번에 발사된다) 실패하지 않기
 * 때문이다. 이 토스트가 뜨는 건 4xx/5xx와 `navigator.onLine === true`인 연결 실패다(실측). */
export const AUTOSAVE_ERROR_TOAST_ID = "builder-autosave-error";

/** 캐릭터/스토리 빌더 공용 자동저장 훅.
 * 필드 변경(subscribe) 시 디바운스 PATCH, "임시저장" 클릭 시 saveNow로 즉시 PATCH.
 *
 * 디바운스된 저장은 사용자가 시작한 게 아니라 호출부에 붙잡을 자리가 없는 유일한 경로다 — 실패를
 * 여기서 알린다(안 그러면 unhandled rejection으로 조용히 사라진다). `saveNow`의 실패는 그대로 던져
 * 호출부("임시저장에 실패했어요")가 처리한다.
 *
 * `save`는 렌더마다 같은 함수여야 디바운스가 성립한다 — 매번 새 함수를 주면 타이머가 매 렌더
 * 새로 만들어져 입력 한 번마다 저장이 나간다.
 *
 * 폼 구독은 렌더마다 끊지 않는다 — 구독이 렌더마다 끊기면 필드 배열 액션(추가·삭제·재정렬)의 변경
 * 알림이 끊긴 틈에 사라져 그 동작이 단독으로는 저장되지 않는다(아래 구독 effect 주석). */
export function useAutosave<TForm, TPayload>(opts: {
  subscribe: (cb: (values: TForm) => void) => () => void;
  formToServer: (values: TForm) => TPayload;
  save: (payload: TPayload) => Promise<unknown>;
  /**
   * 언마운트 시 대기 중이던 저장을 **실행할지**(true) **버릴지**(false). 호출 시점에 평가되므로 최신
   * 상태를 읽는다.
   *
   * 빌더가 이 둘을 갈라야 하는 이유: 초안이 이미 서버에 있으면 실행해야 마지막 편집이
   * 사라지지 않는다("변경사항은 자동으로 저장돼요"라고 화면에 적어 뒀다). 반대로 초안이 아직 없으면
   * 버려야 한다 — 실행하면 스쳐 지나간 방문이 초안을 만들 뿐 아니라, 저장 성공이 URL을 초안 주소로
   * 바꾸면서 **이미 다른 화면에 있는 사용자를 빌더로 되돌려 놓는다**(실측으로 재현했다).
   */
  flushOnUnmount: () => boolean;
  /**
   * 실패 이유에 따라 토스트 문구를 바꿀 때만 준다(없거나 undefined 를 돌려주면 기본 문구). 기다려도 풀리지 않는
   * 실패(다른 창이 먼저 저장해 새로고침이 필요한 경우 등)에 "잠시 후 다시 시도"라고 말하지 않기 위한 자리다.
   * `save` 와 같은 이유로 렌더마다 같은 함수여야 한다.
   */
  errorMessage?: (error: unknown) => string | undefined;
  /**
   * 편집이 들어와 디바운스 저장이 예약될 때마다 부른다(저장 상태를 "저장 대기"로 바꾸는 자리). 호출 시점의 최신 함수를 읽으므로
   * 렌더마다 달라도 디바운스를 다시 만들지 않는다.
   */
  onSchedule?: () => void;
  debounceMs?: number;
}) {
  const debouncedSave = useMemo(
    () =>
      debounce((values: TForm) => {
        void opts
          .save(opts.formToServer(values))
          .catch((error: unknown) => {
            const message =
              opts.errorMessage?.(error) ??
              "자동저장에 실패했어요. 입력한 내용은 그대로 있으니 잠시 후 다시 시도해주세요.";
            toast.error(message, {
              id: AUTOSAVE_ERROR_TOAST_ID,
              duration: Infinity,
              closeButton: true,
            });
          });
      }, opts.debounceMs ?? 1500),
    [opts.save, opts.formToServer, opts.errorMessage, opts.debounceMs],
  );

  // 구독은 `debouncedSave`가 바뀔 때만(사실상 마운트 한 번) 다시 건다. 호출부는 `opts`를 렌더마다 새
  // 객체로 넘기므로 `opts`를 의존성에 두면 셸이 렌더될 때마다 구독이 풀렸다 다시 걸린다. 필드 배열의
  // 추가·삭제·재정렬은 변경 알림을 자식(`useFieldArray`)의 effect에서 보내는데, 같은 커밋에서 셸도 다시
  // 렌더되면 React가 "셸 구독 해제 → 자식 알림 → 셸 재구독" 순으로 돌아 알림이 구독자 없이 사라진다 —
  // 그러면 그 동작은 다음 다른 편집 때까지 저장되지 않고, 그 전에 새로고침하면 유실된다.
  // `subscribe`는 ref로 최신 것을 읽는다.
  const subscribeRef = useRef(opts.subscribe);
  subscribeRef.current = opts.subscribe;
  const onScheduleRef = useRef(opts.onSchedule);
  onScheduleRef.current = opts.onSchedule;

  useEffect(
    () =>
      subscribeRef.current((values) => {
        onScheduleRef.current?.();
        debouncedSave(values);
      }),
    [debouncedSave],
  );

  // `debouncedSave`는 마운트 내내 같은 인스턴스라(위 `save` 계약) 이 정리는 사실상 언마운트에서만 돈다.
  const flushOnUnmountRef = useRef(opts.flushOnUnmount);
  flushOnUnmountRef.current = opts.flushOnUnmount;

  useEffect(
    () => () => {
      // 떠나는 화면의 실패 토스트는 함께 걷는다. 아래 flush가 다시 실패하면 그때 새로 뜬다.
      toast.dismiss(AUTOSAVE_ERROR_TOAST_ID);
      if (flushOnUnmountRef.current()) debouncedSave.flush();
      else debouncedSave.cancel();
    },
    [debouncedSave],
  );

  return {
    saveNow: (values: TForm) => {
      debouncedSave.cancel();
      return opts.save(opts.formToServer(values));
    },
  };
}
