import { useEffect } from "react";

export const ADMIN_APP_NAME = "또나 어드민";

/**
 * 브라우저 탭 제목을 `{화면명} · 또나 어드민`, 대상이 있는 상세는 `{대상 이름} · {화면명} · 또나 어드민` 으로 둔다.
 * 대상 이름은 상세가 불러온 뒤에만 넘긴다 — 그전에는 화면명만 보인다. 화면마다 한 번만 부른다(둘이면 나중에 그린 쪽이
 * 이긴다).
 *
 * 라우트 `head` 가 아니라 효과로 쓰는 이유: 상세 화면은 loader 없이 화면 안의 쿼리로 데이터를 받아, `head` 에서는 대상
 * 이름을 알 수 없다(loader 를 넣으면 진입이 데이터 대기로 바뀌어 머리를 먼저 그리고 본문만 기다리는 동작이 깨진다).
 */
export function useDocumentTitle(screenName: string, targetName?: string) {
  useEffect(() => {
    document.title = [targetName, screenName, ADMIN_APP_NAME].filter(Boolean).join(" · ");
    // 이 훅을 부르지 않는 화면으로 옮겨 가도 앞 화면 이름이 남지 않게 앱 이름으로 되돌린다.
    return () => {
      document.title = ADMIN_APP_NAME;
    };
  }, [screenName, targetName]);
}
