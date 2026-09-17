import { useEffect, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { toast } from "sonner";

import { contentDetailModalAtom, type ContentType } from "@/entities/content";
import { useStartChatMutation } from "@/entities/chat-room";
import { useSessionQuery } from "@/entities/session";

type UsePlayContentOptions = {
  /** 스토리 전용 — 로그인 복귀 후 자동 재생 시 로컬 선택 state도 복원값으로 맞춘다. */
  onRestoreSetup?: (startingSetupId: string) => void;
}

/**
 * techspec-content-detail.md §3 / techspec-chat-common.md §3 — 플레이 버튼의 로그인 유도 +
 * 복귀 후 자동 시작 로직. 캐릭터/스토리 챗 모두 실제 대화방을 생성(`useStartChatMutation`)한 뒤
 * `/chat/$roomId`로 이동한다(스토리는 US-057부터 `contentType: "story"` + `startingSetupId`를 함께 보낸다).
 *
 * 모달 경유(`contentDetailModalAtom`이 차 있음)와 풀페이지 진입을 구분해 히스토리를 다르게 다룬다.
 * `useContentDetailModal.open()`이 라우터를 우회해 `/content/$type/$id` 엔트리를 하나 밀어 넣어두므로,
 * 모달에서 시작한 이동을 push하면 스택이 `[리스트, /content/x, /chat/roomId]`가 되어 채팅에서 뒤로가기가
 * 풀페이지 상세로 튄다. 모달 경유일 때만 `replace`로 그 엔트리를 덮어 뒤로가기가 리스트로 돌아가게 한다.
 */
export function usePlayContent(contentId: string, contentType: ContentType, options?: UsePlayContentOptions) {
  const session = useSessionQuery();
  const navigate = useNavigate();
  const hasAutoStartedRef = useRef(false);
  const isStartingRef = useRef(false);
  const [isStarting, setIsStarting] = useState(false);
  const startChatMutation = useStartChatMutation();
  const [modalState, setModalState] = useAtom(contentDetailModalAtom);
  const isFromModal = modalState !== undefined;

  async function start(startingSetupId?: string) {
    // 연타 방지 — `POST /chat-rooms`에는 유니크 제약이 없어(설계다) 두 번 부르면 오프닝 메시지만 든
    // 빈 방이 하나 더 생기고, 스토리 콘텐츠에는 그 방을 지울 UI가 없다. 호출부의 `aria-disabled`는
    // 포인터만 막고 키보드 Enter는 통과시키므로, 중복 생성을 실제로 막는 건 이 래치다.
    //
    // 반응형 값(`startChatMutation.isPending`·`isStarting`)이 아니라 ref로 잡는 이유 둘:
    // (1) 저 값들은 **렌더 클로저에 박힌 스냅샷**이라, 첫 호출이 일으킨 재렌더가 커밋되기 전에 두 번째
    //     호출이 들어오면(연타·Enter 반복) 같은 `start` 인스턴스가 여전히 false를 읽는다. ref는 렌더를
    //     기다리지 않는 동기 래치라 그 창이 없다.
    // (2) 이 함수는 아래 자동재생 `useEffect`에서도 불린다 = "마운트 시 뮤테이션"이고, `apps/web/CLAUDE.md`는
    //     그 경우 반응형 `isPending` 대신 `mutateAsync`+`await`+로컬 로딩 state를 쓰라고 정해 뒀다
    //     (StrictMode의 마운트→언마운트→재마운트가 `MutationObserver`를 영구 제거해 `isPending`이 그 순간
    //     값에 멈춘다). 선례는 `widgets/builder-preview/ui/PreviewSessionView.tsx`의 `startPreview`다.
    if (isStartingRef.current) return;
    isStartingRef.current = true;
    setIsStarting(true);
    try {
      const room = await startChatMutation.mutateAsync({ contentId, contentType, startingSetupId });
      // 방 생성이 끝난 뒤에 닫는다 — 클릭 즉시 닫으면 생성을 기다리는 동안 아무 피드백 없이 리스트만 보인다.
      setModalState(undefined);
      void navigate({ to: "/chat/$roomId", params: { roomId: room.id }, replace: isFromModal });
    } catch {
      toast.error("대화방을 시작하지 못했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      isStartingRef.current = false;
      setIsStarting(false);
    }
  }

  // 자동재생 effect가 읽을 최신 값을 실어 나르는 ref. `start`도 `options`도 매 렌더 새 참조라 deps에
  // 넣으면 effect가 매 렌더 재실행되고, 안 넣으면 deps가 거짓이 된다. ref 객체는 렌더 간 동일해서
  // deps에서 정직하게 빠진다. 이 동기화 effect가 자동재생 effect보다 **먼저 선언돼 있어야** 마운트
  // 시점에도 최신 값이 먼저 실린다(effect는 선언 순서대로 실행된다).
  const startRef = useRef(start);
  const onRestoreSetupRef = useRef(options?.onRestoreSetup);
  useEffect(() => {
    startRef.current = start;
    onRestoreSetupRef.current = options?.onRestoreSetup;
  });

  useEffect(() => {
    if (hasAutoStartedRef.current) return;
    // 모달 경로에서 렌더링될 때는 매치된 라우트가 홈이라 `useSearch()`를 쓸 수 없어 `window.location.search`를
    // 직접 읽는다(모달·풀페이지 양쪽에서 같게 동작해야 한다 — `clearAutoplayParams`와 같은 이유).
    // 파싱을 effect **안**에서 하므로 매 렌더 새로 만들어지는 `URLSearchParams`가 deps에 올라오지 않는다.
    const params = new URLSearchParams(window.location.search);
    if (params.get("autoplay") !== "1") return;
    if (session.isPending) return; // GET /me 응답을 기다렸다가 한 번만 판단한다(로딩 중엔 항상 session.data가 없다).
    hasAutoStartedRef.current = true;
    if (!session.data) return; // 로그인 리다이렉트 복귀 경로라 이론상 항상 존재하지만 방어적으로 둔다.
    const restoredSetupId = params.get("startingSetupId") ?? undefined;
    if (restoredSetupId) onRestoreSetupRef.current?.(restoredSetupId);
    clearAutoplayParams();
    void startRef.current(restoredSetupId);
    // deps가 정직한 이유: 본문이 읽는 나머지는 전부 ref(렌더 간 동일한 객체)이거나 effect 안에서 직접
    // 읽는 값이라, 이 effect가 실제로 반응해야 할 바깥 값은 세션 둘뿐이다.
  }, [session.isPending, session.data]);

  function handlePlay(startingSetupId?: string) {
    if (!session.data) {
      const query = new URLSearchParams({ autoplay: "1" });
      if (startingSetupId) query.set("startingSetupId", startingSetupId);
      // 로그인 화면 위에 상세 모달이 남지 않게 한다. 히스토리 엔트리는 남겨둔다 —
      // 로그인 후 복귀 지점이 바로 그 `/content/...` 풀페이지라 뒤로가기가 그리 가는 편이 자연스럽다.
      setModalState(undefined);
      void navigate({
        to: "/login",
        search: { redirect: `/content/${contentType}/${contentId}?${query.toString()}` },
      });
      return;
    }
    void start(startingSetupId);
  }

  return {
    handlePlay,
    /** `POST /chat-rooms` 응답 대기 중. 호출부는 이 값으로 **`disabled`가 아니라 `aria-disabled`**를
     * 세운다 — `disabled`는 붙는 즉시 브라우저가 blur해서 누를 때마다 포커스가 `<body>`로 떨어진다
     * (실측 근거는 `entities/content/ui/ContentListLoadMore.tsx`). `aria-disabled`는 포인터만 막으므로
     * `start()` 첫 줄의 early return과 한 짝으로만 성립한다.
     *
     * **대비 한계 — 선례가 이 자리를 보증하지는 않는다.** 호출부가 함께 거는 `aria-disabled:opacity-65`의
     * 65는 위 선례에서 왔지만 **그쪽은 `variant="outline"`**이다. outline은 채움이 곧 페이지 배경이라
     * `opacity`가 텍스트만 흐려 @65%에서도 5.37(라이트)/7.00(다크)로 AA를 지킨다. 반면 **`primary` 솔리드
     * 채움에 거는 건 이 자리(`CharacterPlayBar`·`StoryDetailBody`)가 처음**이라 텍스트와 채움이 같이
     * 배경으로 합성돼 라벨 대비가 약 3.50~3.68:1로 내려간다(oklch→sRGB 계산, 캔버스 실측 아님).
     * `aria-disabled="true"` 비활성 컨트롤이라 WCAG 1.4.3의 inactive component 예외에 들어 위반은 아니다.
     * 포커스 링은 65%에서도 3.36~3.59로 1.4.11(3:1)을 통과한다. */
    isStarting,
  };
}

/**
 * `handlePlay`가 로그인 리다이렉트에 실어 보낸 일회성 파라미터를 소비 직후 URL에서 지운다. 남겨 두면
 * 그 주소가 히스토리에 그대로 박혀 재진입 때 자동재생이 다시 발화할 수 있다.
 *
 * `navigate({replace: true})`를 쓰지 않는 이유는 **히스토리 스택이 달라져서가 아니다.** 라우터의
 * `replace`도 결국 `@tanstack/history`의 `queueHistoryAction("replace", …)` → `win.history.replaceState`라
 * 프로토타입 직호출과 **똑같이 현재 엔트리 하나만** 덮는다 — 뒤로가기 행선지는 두 방법 모두 `/content/x`다
 * (`handlePlay`의 `/login` 이동도 `LoginForm`의 복귀 이동도 push라 `/login`은 한 칸 앞 엔트리에 남는다).
 * 갈리는 건 **알림**이다: 라우터의 `navigate`는 주소 변경을 인지해 재매치·재렌더를 일으키지만,
 * `History.prototype.replaceState` 직호출은 라우터가 `window.history`에 own property로 덮어쓴 래퍼
 * (`onPushPop` → `notify`)를 우회하므로 notify 없이 주소만 청소한다. 자동재생 `useEffect`가 막 발화한
 * 시점이라 재렌더를 유발하지 않는 쪽이 필요하다(`useContentDetailModal`이 `pushState`에 쓰는 수법과 같다).
 * `window.history.state`를 그대로 넘기는 것도 같은 맥락이다 — 라우터의 `stateIndexKey`/`key`가 보존돼
 * `delta` 계산이 어긋나지 않는다.
 *
 * 부작용 1건(이 화면에서는 무해): 우회 때문에 라우터가 캐시한 `currentLocation`에는 `?autoplay=1`이 남는다.
 * `content.$type.$id`에 `validateSearch`가 없고 이 페이지에서 `useSearch()`를 읽는 코드가 0건이며 모든
 * navigate/Link가 절대 경로라 그 값을 읽는 쪽이 없기 때문이다 — **이 라우트에 `validateSearch`가 생기면
 * 이 전제가 깨진다.**
 */
function clearAutoplayParams() {
  const params = new URLSearchParams(window.location.search);
  params.delete("autoplay");
  params.delete("startingSetupId");
  const query = params.toString();
  History.prototype.replaceState.call(
    window.history,
    window.history.state,
    "",
    query ? `${window.location.pathname}?${query}` : window.location.pathname,
  );
}
