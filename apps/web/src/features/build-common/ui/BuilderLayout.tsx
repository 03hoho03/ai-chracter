import type { ReactNode } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";

type BuilderLayoutProps = {
  /** 폼 열 콘텐츠(헤더·탭 등 — 기존 Shell이 `<main>`에 직접 그리던 것 전부). */
  children: ReactNode;
  /** 1280px 이상에서 폼 열 왼쪽에 세우는 묶음 목록(`BuilderStepNav` 의 `column`). 그보다 좁으면 숨는다. */
  steps: ReactNode;
  /** 프리뷰 열 콘텐츠. Shell이 정한 미리보기 열 내용(대개 `renderPreview` 결과)을 넘긴다 — `widgets/builder-preview`를
   * 여기서 import하지 않는다("Shell은 renderPreview만 알고 프리뷰 위젯을
   * 직접 import하지 않는다"). */
  preview: ReactNode;
  /** lg 미만에서 폼 대신 프리뷰를 전체화면으로 보여줄지([미리보기]를 열었거나 테스트를 골랐을 때). lg 이상에서는 테스트를
   * 고르면 true 가 되지만 `lg:` 클래스(`lg:flex`·`lg:block`·`lg:max-w-none`)가 덮어 열들이 그대로 함께 보인다. */
  isPreviewOpen: boolean;
};

/**
 * 빌더 그리드 셸 — lg 2단, xl 3단(묶음 열·폼·미리보기).
 *
 * lg 미만은 가운데 정렬된 `max-w-2xl`이고 폼·프리뷰 중 하나만 화면에 보인다(`isPreviewOpen`이
 * 어느 쪽을 보일지 정한다 — 미리보기를 열면 상한 없이 전체화면). lg 이상은 상한을 걷고 왼쪽부터
 * 채우는 그리드다. lg~xl(1024~1279px)은 2단이다: 폼 열은 `42rem`(=`max-w-2xl`)이고, 폼 열 `px-6`이 상단바의 `px-6`과 같아
 * 폼 열 첫 줄(묶음 줄) left가 뒤로가기 버튼 left와 맞는다. xl(1280px) 이상은 폼 열 왼쪽에 176px 묶음 열을 더한 3단이다 — 묶음 열이
 * 같은 `pl-6` 으로 뒤로가기 left를 이어받고, 오른쪽 `border-r` 로 폼 열과 맞붙는다. 폼 열과 미리보기 사이 24px는 미리보기 칸의
 * 왼쪽 여백(`xl:ml-6`)이 맡는다 — 그리드 `gap` 으로 두면 묶음 열과 폼 열 사이도 함께 벌어진다. 묶음 열을 붙여도 폼 열이 `42rem`을
 * 지키는 하한은 176 + 672 + 24 + 320 = 1192px 라 xl 위에서는 늘 지켜진다. 묶음 열을 lg부터 두지 않는 이유가 그것이다 — 1024px에서
 * 붙이면 폼 열이 504px까지 줄어, 빌더가 좌측 패널을 그리지 않는 근거로 든 폼 폭을 빌더 자신의 열이 먹는다.
 *
 * 프리뷰는 나머지 트랙(`1fr`, xl은 하한 320px) 안에서
 * `max-w-4xl`로 묶여 그 오른쪽은 비워 둔다 — 실제 채팅 문단 상한(768px)에 좌우 여백을 더한 폭을 담는
 * 가장 작은 값이다. 칸이 이 상한까지 자라는 넓은 화면(lg~xl 2단이면 약 1600px, xl 3단이면 약 1770px 이상)에서만 미리보기 줄 길이가
 * 실제 채팅과 같고, 그보다 좁으면 칸이 상한에 못 미쳐 줄이 더 짧다. 상한을 트랙(`minmax(0,…)`)에 걸지 않고
 * 칸에 거는 이유: 두 트랙이 모두 고정 상한이면 그리드가 남는 폭을 두 트랙에 나눠 키워 1024~1368px에서
 * 폼 열이 `42rem`보다 좁아진다. `1fr` 트랙은 폼 열이 먼저 `42rem`을 채운 뒤에야 자란다.
 * **프리뷰 열은 lg 미만에서 `hidden`이지 언마운트가 아니다** — 트리에는 있고 화면에만 없다. 프리뷰
 * 세션은 지연 시작이라 마운트만으로는 세션을 만들지 않으므로 이 비용은 0이다. **묶음 열도 같다** — xl 미만에서 `hidden`이지
 * 언마운트가 아니다. 폭에 따라 JS로 넣고 빼면 `<main>` 자식 자리가 바뀌어 폼 열과 미리보기가 다시 마운트되고 입력·포커스·대화를 잃는다.
 *
 * 세로로는 lg 이상에서만 폼 열 윗여백을 `pt-6`으로 줄여 상단바와 묶음 줄 사이를 24px로 둔다(탭 목록과
 * 탭 본문 사이는 셸의 `Tabs`가 맡는다). xl 이상은 폼 열에 탭 줄이 없어 첫 내용이 윗여백 24px + 탭 본문 루트의 `py-6` 24px 아래에
 * 서므로, 묶음 열도 윗여백을 48px(`pt-12`)로 두어 첫 묶음 줄과 첫 칸이 같은 높이에서 시작한다. lg 미만은 페이지 표준 관용구(`py-10`) 그대로다.
 *
 * 분기는 CSS `lg:`·`xl:`다(JS `useMedia` 아님) — 채팅 더보기 패널이 JS를 쓴 이유는 `Sheet`가 body로
 * 포털되기 때문인데(DESIGN.md Navigation 절) 이 프리뷰 열과 묶음 열은 포털 없이 in-flow라 그 제약이 없다.
 *
 * `min-h-0`(그리드 자식의 기본 `min-height:auto`를 되돌린다) + `overflow-y-auto`가 없으면 열들이
 * 콘텐츠 높이만큼 늘어나 페이지 전체가 스크롤된다 — `lg:h-below-header`로
 * 그리드 행 자체를 뷰포트 높이에 고정하고, 각 열에 그 두 클래스를 걸어 열 내부만 스크롤되게 한다.
 *
 * 폼 열의 `lg:relative`는 그 안의 `sr-only`(`position: absolute`) 요소들이 이 스크롤 상자를 기준으로
 * 잡게 한다. 없으면 기준이 문서가 되어, 글자 수 화면 밖 접두처럼 폼 아래쪽에 놓인 그 요소들이 상자에
 * 잘리지 않은 채 문서 높이를 늘린다. 그러면 폼 열을 끝까지 내린 뒤 더 굴릴 때 문서가 스크롤되어 폼·미리보기
 * 두 열이 함께 위로 밀려 올라가고 아래가 빈 화면이 된다. 묶음 열의 `relative` 도 같은 이유다(줄마다 `sr-only` 접미가 있다).
 */
export function BuilderLayout({ children, steps, preview, isPreviewOpen }: BuilderLayoutProps) {
  return (
    <main
      className={cn(
        "mx-auto lg:grid lg:h-below-header lg:max-w-none lg:grid-cols-[minmax(0,42rem)_1fr] lg:gap-6",
        "xl:grid-cols-[176px_minmax(0,42rem)_minmax(320px,1fr)] xl:gap-0",
        // lg 미만에서 미리보기를 열면 전체화면이라 폭 상한을 뗀다. lg 이상은 위 `lg:max-w-none`이 덮는다.
        !isPreviewOpen && "max-w-2xl",
      )}
    >
      <div className="relative hidden min-h-0 overflow-y-auto border-r border-border pt-12 pr-3 pb-10 pl-6 xl:block">{steps}</div>
      <div
        className={cn(
          "flex-col gap-6 px-4 sm:px-6 py-10 lg:pt-6 lg:relative lg:flex lg:min-h-0 lg:overflow-y-auto",
          isPreviewOpen ? "hidden" : "flex",
        )}
      >
        {children}
      </div>
      <div
        className={cn(
          "lg:min-h-0 lg:max-w-4xl lg:overflow-y-auto xl:ml-6",
          isPreviewOpen ? "block" : "hidden lg:block",
        )}
      >
        {preview}
      </div>
    </main>
  );
}
