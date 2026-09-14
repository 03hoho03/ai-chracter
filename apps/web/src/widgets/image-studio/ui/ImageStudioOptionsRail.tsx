import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@ai-character-chat/ui/components/sheet";

import { GenerateImagesOptionsFields } from "@/features/generate-images";

import { useIsImageStudioWideLayout } from "../lib/useIsImageStudioWideLayout";

// image-refact-techspec.md IT-8 — 열 껍데기는 ImageStudioShell이 CSS `lg:`로 그리고, 이 컴포넌트는
// 그 안의 "내용"만 결정한다(ImageStudioLibraryRail과 같은 구조). GenerateImagesOptionsFields는
// useFormContext로 상위 GenerateImagesFormProvider를 읽으므로, 인라인이든 시트(포털)든 React 트리상
// 그 아래에 있기만 하면 된다(DOM 위치와 무관 — image-refact-techspec.md IT-9).
export function ImageStudioOptionsRail({
  isOpen,
  onOpenChange,
}: {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
}) {
  const isWide = useIsImageStudioWideLayout();

  if (isWide) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <GenerateImagesOptionsFields />
      </div>
    );
  }

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange}>
      {/* image-refact-goal-prompt.md IR-6 — 옵션 시트는 콘텐츠 높이(비율 6 + 개수 2라 짧다).
          SheetContent 기본값(data-[side=bottom]:h-auto)을 그대로 둔다. */}
      <SheetContent
        side="bottom"
        className="rounded-t-xl"
        // 브라우저 실검증(S6) — ImageStudioLibraryRail과 같은 이유. 셸의 별도 버튼이 열어서
        // SheetTrigger의 자동 포커스 복원 대상이 없다.
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          document.querySelector<HTMLElement>('[data-image-studio-trigger="options"]')?.focus();
        }}
      >
        <SheetHeader>
          <SheetTitle>생성 옵션</SheetTitle>
        </SheetHeader>
        <div className="p-4">
          <GenerateImagesOptionsFields />
        </div>
      </SheetContent>
    </Sheet>
  );
}
