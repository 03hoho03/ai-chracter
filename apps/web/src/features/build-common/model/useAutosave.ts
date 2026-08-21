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
 * 않은 걸 모른 채 탭을 닫는다. 해제는 다음 저장 성공(`dismiss`)과 빌더 이탈 두 가지다. 성공 토스트는
 * 띄우지 않는다 — 1.5초마다 초록 토스트가 뜨면 재앙이다.
 *
 * 참고: 진짜 오프라인에서는 이 토스트가 뜨지 않는다. `app/providers.tsx`의 `QueryClient`가 기본
 * `networkMode: "online"`이라 뮤테이션이 **pause**되고(재접속 시 한꺼번에 발사된다) 실패하지 않기
 * 때문이다. 이 토스트가 뜨는 건 4xx/5xx와 `navigator.onLine === true`인 연결 실패다(실측). */
const AUTOSAVE_ERROR_TOAST_ID = "builder-autosave-error";

/** techspec-builder-common.md §1 — 캐릭터/스토리 빌더 공용 자동저장 훅.
 * 필드 변경(subscribe) 시 디바운스 PATCH, "임시저장" 클릭 시 saveNow로 즉시 PATCH.
 *
 * 디바운스된 저장은 사용자가 시작한 게 아니라 호출부에 붙잡을 자리가 없는 유일한 경로다 — 실패를
 * 여기서 알린다(안 그러면 unhandled rejection으로 조용히 사라진다). `saveNow`의 실패는 그대로 던져
 * 호출부("임시저장에 실패했어요")가 처리한다.
 *
 * `save`는 렌더마다 같은 함수여야 디바운스가 성립한다 — 매번 새 함수를 주면 타이머가 매 렌더
 * 새로 만들어져 입력 한 번마다 저장이 나간다. */
export function useAutosave<TForm, TPayload>(opts: {
  subscribe: (cb: (values: TForm) => void) => () => void;
  formToServer: (values: TForm) => TPayload;
  save: (payload: TPayload) => Promise<unknown>;
  /**
   * 언마운트 시 대기 중이던 저장을 **실행할지**(true) **버릴지**(false). 호출 시점에 평가되므로 최신
   * 상태를 읽는다.
   *
   * 빌더가 이 둘을 갈라야 하는 이유(US-007): 초안이 이미 서버에 있으면 실행해야 마지막 편집이
   * 사라지지 않는다("변경사항은 자동으로 저장돼요"라고 화면에 적어 뒀다). 반대로 초안이 아직 없으면
   * 버려야 한다 — 실행하면 스쳐 지나간 방문이 초안을 만들 뿐 아니라, 저장 성공이 URL을 초안 주소로
   * 바꾸면서 **이미 다른 화면에 있는 사용자를 빌더로 되돌려 놓는다**(실측으로 재현했다).
   */
  flushOnUnmount: () => boolean;
  debounceMs?: number;
}) {
  const debouncedSave = useMemo(
    () =>
      debounce((values: TForm) => {
        void opts
          .save(opts.formToServer(values))
          .then(() => toast.dismiss(AUTOSAVE_ERROR_TOAST_ID))
          .catch(() => {
            toast.error("자동저장에 실패했어요. 입력한 내용은 그대로 있으니 잠시 후 다시 시도해주세요.", {
              id: AUTOSAVE_ERROR_TOAST_ID,
              duration: Infinity,
              closeButton: true,
            });
          });
      }, opts.debounceMs ?? 1500),
    [opts.save, opts.formToServer, opts.debounceMs],
  );

  useEffect(() => opts.subscribe(debouncedSave), [opts, debouncedSave]);

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
