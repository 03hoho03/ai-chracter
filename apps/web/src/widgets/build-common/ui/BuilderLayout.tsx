import type { ReactNode } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";

type BuilderLayoutProps = {
  /** 폼 열 콘텐츠(헤더·탭 등 — 기존 Shell이 `<main>`에 직접 그리던 것 전부). */
  children: ReactNode;
  /** 프리뷰 열 콘텐츠. Shell이 `renderPreview`로 받은 노드를 그대로 넘긴다 — `widgets/builder-preview`를
   * 여기서 import하지 않는다(builder-techspec.md §2, "Shell은 renderPreview만 알고 프리뷰 위젯을
   * 직접 import하지 않는다"). */
  preview: ReactNode;
  /** lg 미만에서 폼 대신 프리뷰를 전체화면으로 보여줄지(D-1). lg 이상에서는 두 열이 항상 함께 보이므로
   * 무시된다 — [미리보기] 버튼이 `lg:hidden`이라 그 폭에서는 이 값이 true가 될 경로가 없다. */
  isPreviewOpen: boolean;
};

/**
 * builder-techspec.md §5(T-5, T-6) — 빌더 2단 그리드 셸.
 *
 * lg 미만은 현행 폭(`max-w-2xl`)을 그대로 쓰고 폼·프리뷰 중 하나만 화면에 보인다(D-1, 모바일
 * 미변경 — `isPreviewOpen`이 어느 쪽을 보일지 정한다). lg 이상은 `max-w-7xl` 2단 그리드로 풀고 폼
 * 열은 `max-w-2xl`(=`42rem`)을 유지한 채 나머지를 프리뷰 열이 쓴다. **프리뷰 열은 lg 미만에서
 * `hidden`이지 언마운트가 아니다** — 트리에는 있고 화면에만 없다. D-7(프리뷰 세션 지연 시작)이
 * 마운트만으로는 세션을 만들지 않기로 정했으므로(techspec §5-2) 이 비용은 0이다.
 *
 * 분기는 CSS `lg:`다(JS `useMedia` 아님, T-6) — 채팅 더보기 패널이 JS를 쓴 이유는 `Sheet`가 body로
 * 포털되기 때문인데(DESIGN.md §Navigation) 이 프리뷰 열은 포털 없이 in-flow라 그 제약이 없다.
 *
 * `min-h-0`(그리드 자식의 기본 `min-height:auto`를 되돌린다) + `overflow-y-auto`가 없으면 두 열이
 * 콘텐츠 높이만큼 늘어나 페이지 전체가 스크롤된다(techspec §5-3) — `lg:h-[calc(100dvh-3.5rem)]`로
 * 그리드 행 자체를 뷰포트 높이에 고정하고, 각 열에 그 두 클래스를 걸어 열 내부만 스크롤되게 한다.
 */
export function BuilderLayout({ children, preview, isPreviewOpen }: BuilderLayoutProps) {
  return (
    <main
      className={cn(
        "mx-auto lg:grid lg:h-[calc(100dvh-3.5rem)] lg:max-w-7xl lg:grid-cols-[minmax(0,42rem)_1fr] lg:gap-6",
        !isPreviewOpen && "max-w-2xl",
      )}
    >
      <div
        className={cn(
          "flex-col gap-6 px-4 sm:px-6 py-10 lg:flex lg:min-h-0 lg:overflow-y-auto",
          isPreviewOpen ? "hidden" : "flex",
        )}
      >
        {children}
      </div>
      <div
        className={cn("lg:min-h-0 lg:overflow-y-auto", isPreviewOpen ? "block" : "hidden lg:block")}
      >
        {preview}
      </div>
    </main>
  );
}
