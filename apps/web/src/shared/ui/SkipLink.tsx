import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";

/**
 * 전역 크롬이 있는 화면의 첫 Tab 정지. 좌측 패널(내비 + 최근 대화)과 헤더가 본문 앞에 Tab 정지를 많이 두므로 그것을 한
 * 번에 건너뛴다. 쉬는 동안은 화면 위로 밀려 있다가 포커스를 받으면 내려온다(움직임이 아니라 자리 바꿈이라 전환이 없다).
 * 해시 이동을 라우터가 히스토리 항목으로 쌓지 않도록 기본 동작을 막고 본문 래퍼에 직접 포커스를 준다 — 다음 Tab 은
 * 본문 첫 요소부터다. 불투명 1px 테두리(`border-ring`)가 포커스 표시의 3:1 을 진다(DESIGN.md Do's and Don'ts).
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
