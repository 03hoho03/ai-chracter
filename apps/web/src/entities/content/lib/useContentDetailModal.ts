import { useEffect } from "react";
import { useAtom } from "jotai";

import { contentDetailModalAtom } from "../model/atoms";
import type { ContentType } from "../model/content";
import { pickDetailModalReturnFocus } from "../model/detailModalReturnFocus";

/**
 * 모달이 닫힌 뒤 포커스를 돌려줄 자리. 상세 모달은 `DialogTrigger` 없이 열려(카드가 아톰을 채운다) Radix 가 닫힐 때
 * 보낼 곳이 없고, 포커스가 `<body>` 로 떨어진다 — Callable 래퍼(`createCallable`)가 푼 것과 같은 뿌리다. 그래서
 * 연 순간의 포커스 요소를 여기 기억했다가 `ContentDetailModalOutlet` 이 닫힐 때 꺼내 쓴다.
 *
 * 아톰이 아니라 모듈에 두는 이유: 모달은 앱에 하나(`routes/__root.tsx`)이고, 닫히면 아톰은 곧바로 비지만 포커스를
 * 돌려줄 시점(닫힘 애니메이션이 끝나 내용이 사라질 때)은 그 뒤다. `isPlainClose` 는 `close()`(✕·Esc·바깥 클릭)와
 * 브라우저 뒤로가기만 세운다 — 작가·해시태그·플레이처럼 다른 화면으로 가며 아톰을 직접 비우는 곳은 세우지 않는다.
 */
const returnFocus: {
  opener: HTMLElement | null;
  getFallback: (() => HTMLElement | null) | undefined;
  isPlainClose: boolean;
} = { opener: null, getFallback: undefined, isPlainClose: false };

/** 닫힌 모달이 포커스를 돌려줄 요소를 꺼내고 기억을 비운다. 돌려주지 않을 때는 `null`. */
export function takeDetailModalReturnFocus(): HTMLElement | null {
  const target = pickDetailModalReturnFocus({
    isPlainClose: returnFocus.isPlainClose,
    opener: returnFocus.opener,
    fallback: returnFocus.getFallback?.() ?? null,
  });
  returnFocus.opener = null;
  returnFocus.getFallback = undefined;
  returnFocus.isPlainClose = false;
  return target;
}

type OpenOptions = {
  /** 연 요소가 닫힐 때 사라졌으면 대신 받을 곳. 없으면 그때는 돌려주지 않는다. */
  getFallbackFocus?: () => HTMLElement | null;
};

/**
 * 카드 클릭 시 페이지 전환 없이 모달로 여는 훅. `open()`은
 * URL만 `pushState`로 갱신(실제 라우터 네비게이션 아님)하고, `close()`는 `history.back()`으로
 * 그 엔트리를 되돌린다. 브라우저 뒤로가기(popstate)로 닫힌 경우엔 모달 상태만 지우고 라우터
 * 네비게이션은 일으키지 않는다(직접 진입 시에만 `routes/content.$type.$id.tsx`가 매치된다).
 *
 * TanStack Router의 `createBrowserHistory`는 `window.history.pushState`/`replaceState`
 * 인스턴스 프로퍼티 자체를 감시용 래퍼로 덮어써서, 평범한 `window.history.pushState(...)`
 * 호출도 실제 라우트 매치를 일으켜버린다(실측 확인 — 모달이 열리면서 리스트 페이지가
 * 언마운트되고 풀페이지 라우트가 함께 렌더링됐다). 그 래퍼는 `history` 인스턴스의 own
 * property일 뿐 `History.prototype.pushState`는 건드리지 않으므로, 프로토타입 메서드를
 * 직접 호출해 래퍼를 우회한다 — 라우터는 이 호출을 알지 못해 재매치하지 않는다.
 */
export function useContentDetailModal() {
  const [state, setState] = useAtom(contentDetailModalAtom);

  function open(type: ContentType, id: string, options?: OpenOptions) {
    const active = document.activeElement;
    returnFocus.opener = active instanceof HTMLElement && active !== document.body ? active : null;
    returnFocus.getFallback = options?.getFallbackFocus;
    returnFocus.isPlainClose = false;
    setState({ type, id });
    History.prototype.pushState.call(window.history, window.history.state, "", `/content/${type}/${id}`);
  }

  function close() {
    returnFocus.isPlainClose = true;
    setState(undefined);
    window.history.back();
  }

  useEffect(() => {
    if (!state) return;
    const handlePopState = () => {
      returnFocus.isPlainClose = true;
      setState(undefined);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [state, setState]);

  return { state, open, close };
}
