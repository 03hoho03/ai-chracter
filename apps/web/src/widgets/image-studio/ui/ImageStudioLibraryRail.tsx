import { useAtom } from "jotai";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@ai-character-chat/ui/components/sheet";

import { useIsImageStudioWideLayout } from "../lib/useIsImageStudioWideLayout";
import { imageStudioLibrarySheetOpenAtom } from "../model/atoms";
import { GeneratedImageLibraryPanel } from "./GeneratedImageLibraryPanel";

// image-refact-techspec.md IT-8 — 열 껍데기(<aside>, 폭, 보더)는 ImageStudioShell이 CSS `lg:`로
// 이미 그려 두고, 이 컴포넌트는 그 안에 꽂히는 "내용"만 결정한다. ChatMorePanel/ChatMoreSidebar가
// 같은 boolean으로 각자 "내가 렌더될지"를 판정하는 구조를 그대로 베낀다 — 어느 쪽이든
// GeneratedImageLibraryPanel은 한 곳에만 마운트된다(image-refact-goal-prompt.md IR-5, §2-6:
// 쿼리가 이중으로 나가는 게 아니라 DOM에 두 벌 남는 게 문제다).
export function ImageStudioLibraryRail() {
  const isWide = useIsImageStudioWideLayout();
  const [isOpen, setIsOpen] = useAtom(imageStudioLibrarySheetOpenAtom);

  if (isWide) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {/* image-refact-goal-prompt.md IR-3 — 좌열 p-4(208px 콘텐츠) → grid-cols-2 고정으로
            98×98 정사각 타일. 기본값(sm:/md: 이스케일)은 뷰포트 폭 기준이라 이 고정폭 레일에
            그대로 두면 lg 이상에서 그대로 걸려 4열까지 욱여넣는다(GeneratedImageLibraryPanel.tsx
            상단 주석). */}
        <GeneratedImageLibraryPanel gridColumnsClassName="grid-cols-2" />
      </div>
    );
  }

  return (
    <Sheet open={isOpen} onOpenChange={setIsOpen}>
      {/* image-refact-goal-prompt.md IR-6 — 보관함 시트는 헤더 아래까지(긴 그리드). ChatMorePanel의
          top-[118px]은 전역 헤더 + 채팅 헤더를 뺀 값이라 여기엔 안 맞는다(우리 크롬은 h-14 하나뿐).
          정확한 값은 브라우저 실측으로 정하기로 하고 지금은 top-14로 둔다. */}
      <SheetContent
        side="bottom"
        className="top-14 rounded-t-xl"
        // 브라우저 실검증(S6) — 이 시트는 SheetTrigger가 아니라 셸의 별도 버튼이 setIsOpen(true)로
        // 여는데, radix Dialog는 SheetTrigger로 열렸을 때만 트리거에 포커스를 자동 복원한다.
        // 트리거가 시트 트리 밖에 있어 복원 대상이 없으므로 직접 지정한다.
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          document.querySelector<HTMLElement>('[data-image-studio-trigger="library"]')?.focus();
        }}
      >
        <SheetHeader>
          <SheetTitle>보관함</SheetTitle>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <GeneratedImageLibraryPanel onNavigateToGenerate={() => setIsOpen(false)} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
