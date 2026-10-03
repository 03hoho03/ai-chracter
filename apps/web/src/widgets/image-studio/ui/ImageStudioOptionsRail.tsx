import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@ai-character-chat/ui/components/sheet";

import {
  GenerateImagesOptionsFields,
  GenerateImagesStyleGrid,
  useGenerateImagesSubmit,
} from "@/features/generate-images";

import { useIsImageStudioWideLayout } from "../lib/useIsImageStudioWideLayout";

// 열 껍데기는 ImageStudioShell이 CSS `lg:`로 그리고, 이 컴포넌트는
// 그 안의 "내용"만 결정한다(ImageStudioLibraryRail과 같은 구조). GenerateImagesOptionsFields는
// useFormContext로 상위 GenerateImagesFormProvider를 읽으므로, 인라인이든 시트(포털)든 React 트리상
// 그 아래에 있기만 하면 된다(DOM 위치와 무관). 스타일 그리드도 같은 이유로 두 분기 모두에서
// 옵션 필드 아래에 둔다 — 그리드 열 수는 자리마다 달라 `layout`으로 알려 준다.
//
// 이용 불가(모델 목록 실패·빈 목록·전 모델 불가)면 스타일 섹션을 숨긴다. 목록 조회가 실패하면
// 모델 목록이 끝내 오지 않아 그리드가 스켈레톤을 영원히 펄스하고, 빈 목록·전 모델 불가에서는 고를
// 스타일이 없다. 그 사유는 중앙 열의 대체 화면이 알린다.
export function ImageStudioOptionsRail({
  isOpen,
  onOpenChange,
}: {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
}) {
  const isWide = useIsImageStudioWideLayout();
  const { unavailableReason } = useGenerateImagesSubmit();
  const isStyleSectionVisible = unavailableReason === undefined;

  if (isWide) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <GenerateImagesOptionsFields />
        {isStyleSectionVisible && <GenerateImagesStyleGrid layout="rail" />}
      </div>
    );
  }

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange}>
      {/* 옵션 시트는 콘텐츠 높이다 — SheetContent 기본값(data-[side=bottom]:h-auto)을 그대로
          두고 높이 상한도 내부 스크롤도 걸지 않았다. 비율·개수 아래에 스타일 그리드가 들어와
          좁은 화면에서는 시트가 화면 높이에 가깝거나 넘을 만큼 길다. */}
      <SheetContent
        side="bottom"
        className="rounded-t-xl"
        // 브라우저 실검증 — ImageStudioLibraryRail과 같은 이유. 셸의 별도 버튼이 열어서
        // SheetTrigger의 자동 포커스 복원 대상이 없다.
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          document.querySelector<HTMLElement>('[data-image-studio-trigger="options"]')?.focus();
        }}
      >
        <SheetHeader>
          <SheetTitle>생성 옵션</SheetTitle>
        </SheetHeader>
        <div className="flex flex-col gap-4 p-4">
          <GenerateImagesOptionsFields />
          {isStyleSectionVisible && <GenerateImagesStyleGrid layout="sheet" />}
        </div>
      </SheetContent>
    </Sheet>
  );
}
