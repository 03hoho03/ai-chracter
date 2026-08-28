import { useEffect } from "react";
import { useAtom } from "jotai";

import { contentDetailModalAtom } from "@/shared/model/content-detail-modal";

/**
 * techspec-content-detail.md §1 — 카드 클릭 시 페이지 전환 없이 모달로 여는 훅. `open()`은
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

  function open(type: "character" | "story", id: string) {
    setState({ type, id });
    History.prototype.pushState.call(window.history, window.history.state, "", `/content/${type}/${id}`);
  }

  function close() {
    setState(null);
    window.history.back();
  }

  useEffect(() => {
    if (!state) return;
    const onPopState = () => setState(null);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [state, setState]);

  return { state, open, close };
}
