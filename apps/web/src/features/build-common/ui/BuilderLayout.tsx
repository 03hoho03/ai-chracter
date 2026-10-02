import type { ReactNode } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";

type BuilderLayoutProps = {
  /** 폼 열 콘텐츠(헤더·탭 등 — 기존 Shell이 `<main>`에 직접 그리던 것 전부). */
  children: ReactNode;
  /** 프리뷰 열 콘텐츠. Shell이 정한 미리보기 열 내용(대개 `renderPreview` 결과)을 넘긴다 — `widgets/builder-preview`를
   * 여기서 import하지 않는다("Shell은 renderPreview만 알고 프리뷰 위젯을
   * 직접 import하지 않는다"). */
  preview: ReactNode;
  /** lg 미만에서 폼 대신 프리뷰를 전체화면으로 보여줄지. lg 이상에서는 두 열이 항상 함께 보이므로
   * 무시된다 — [미리보기] 버튼이 `lg:hidden`이라 그 폭에서는 이 값이 true가 될 경로가 없다. */
  isPreviewOpen: boolean;
};

/**
 * 빌더 2단 그리드 셸.
 *
 * lg 미만은 가운데 정렬된 `max-w-2xl`이고 폼·프리뷰 중 하나만 화면에 보인다(`isPreviewOpen`이
 * 어느 쪽을 보일지 정한다 — 미리보기를 열면 상한 없이 전체화면). lg 이상은 상한을 걷고 왼쪽부터
 * 채우는 2단 그리드다: 폼 열은 `42rem`(=`max-w-2xl`)이고, 폼 열 `px-6`이 상단바의 `px-6`과 같아 탭
 * 목록 left가 어느 폭에서나 뒤로가기 버튼 left와 맞는다. 프리뷰는 나머지 트랙(`1fr`) 안에서
 * `max-w-4xl`로 묶여 그 오른쪽은 비워 둔다 — 실제 채팅 문단 상한(768px)에 좌우 여백을 더한 폭을 담는
 * 가장 작은 값이다. 칸이 이 상한까지 자라는 넓은 화면(약 1600px 이상)에서만 미리보기 줄 길이가 실제
 * 채팅과 같고, 그보다 좁으면 칸이 상한에 못 미쳐 줄이 더 짧다. 상한을 트랙(`minmax(0,…)`)에 걸지 않고
 * 칸에 거는 이유: 두 트랙이 모두 고정 상한이면 그리드가 남는 폭을 두 트랙에 나눠 키워 1024~1368px에서
 * 폼 열이 `42rem`보다 좁아진다. `1fr` 트랙은 폼 열이 먼저 `42rem`을 채운 뒤에야 자란다.
 * **프리뷰 열은 lg 미만에서 `hidden`이지 언마운트가 아니다** — 트리에는 있고 화면에만 없다. 프리뷰
 * 세션은 지연 시작이라 마운트만으로는 세션을 만들지 않으므로 이 비용은 0이다.
 *
 * 세로로는 lg 이상에서만 폼 열 윗여백을 `pt-6`으로 줄여 상단바와 탭 목록 사이를 24px로 둔다(탭 목록과
 * 탭 본문 사이는 셸의 `Tabs`가 맡는다). lg 미만은 페이지 표준 관용구(`py-10`) 그대로다.
 *
 * 분기는 CSS `lg:`다(JS `useMedia` 아님) — 채팅 더보기 패널이 JS를 쓴 이유는 `Sheet`가 body로
 * 포털되기 때문인데(DESIGN.md §Navigation) 이 프리뷰 열은 포털 없이 in-flow라 그 제약이 없다.
 *
 * `min-h-0`(그리드 자식의 기본 `min-height:auto`를 되돌린다) + `overflow-y-auto`가 없으면 두 열이
 * 콘텐츠 높이만큼 늘어나 페이지 전체가 스크롤된다 — `lg:h-below-header`로
 * 그리드 행 자체를 뷰포트 높이에 고정하고, 각 열에 그 두 클래스를 걸어 열 내부만 스크롤되게 한다.
 */
export function BuilderLayout({ children, preview, isPreviewOpen }: BuilderLayoutProps) {
  return (
    <main
      className={cn(
        "mx-auto lg:grid lg:h-below-header lg:max-w-none lg:grid-cols-[minmax(0,42rem)_1fr] lg:gap-6",
        // lg 미만에서 미리보기를 열면 전체화면이라 폭 상한을 뗀다. lg 이상은 위 `lg:max-w-none`이 덮는다.
        !isPreviewOpen && "max-w-2xl",
      )}
    >
      <div
        className={cn(
          "flex-col gap-6 px-4 sm:px-6 py-10 lg:pt-6 lg:flex lg:min-h-0 lg:overflow-y-auto",
          isPreviewOpen ? "hidden" : "flex",
        )}
      >
        {children}
      </div>
      <div
        className={cn("lg:min-h-0 lg:max-w-4xl lg:overflow-y-auto", isPreviewOpen ? "block" : "hidden lg:block")}
      >
        {preview}
      </div>
    </main>
  );
}
