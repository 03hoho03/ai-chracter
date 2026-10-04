import { MAIN_CONTENT_ID } from "../config/landmarks";

/**
 * 문서의 첫 Tab 정지. 쉬는 동안은 화면 위로 밀려 있다가 포커스를 받으면 내려온다. 해시 이동을 라우터가
 * 히스토리 항목으로 쌓지 않도록 기본 동작을 막고 본문에 직접 포커스를 준다 — 다음 Tab 은 본문 첫 요소부터다.
 */
export function SkipLink() {
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      onClick={(event) => {
        event.preventDefault();
        document.getElementById(MAIN_CONTENT_ID)?.focus();
      }}
      className="fixed top-2 left-2 z-50 -translate-y-[calc(100%+1rem)] rounded-lg border border-ring bg-background px-3 py-2 text-sm font-medium text-foreground focus:translate-y-0 focus:ring-3 focus:ring-ring/50 focus:outline-none"
    >
      본문으로 건너뛰기
    </a>
  );
}
