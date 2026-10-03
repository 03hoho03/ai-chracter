import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@ai-character-chat/ui/components/sheet";
import { useRef } from "react";

import {
  GenerateImagesOptionsFields,
  GenerateImagesStyleGrid,
  useGenerateImagesSubmit,
} from "@/features/generate-images";

import { useIsImageStudioWideLayout } from "../lib/useIsImageStudioWideLayout";

// 옵션 시트를 어느 트리거로 열었나 — 옵션 아이콘 버튼("options") 또는 스타일 선택 버튼("style").
// 값은 data-image-studio-trigger 표식과 같아 닫힘 포커스가 그대로 선택자에 쓴다.
export type OptionsSheetEntry = "options" | "style";

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
  entry,
  onOpenChange,
}: {
  isOpen: boolean;
  entry: OptionsSheetEntry;
  onOpenChange: (isOpen: boolean) => void;
}) {
  const isWide = useIsImageStudioWideLayout();
  const { unavailableReason } = useGenerateImagesSubmit();
  const isStyleSectionVisible = unavailableReason === undefined;
  const sheetBodyRef = useRef<HTMLDivElement>(null);
  const styleSectionRef = useRef<HTMLDivElement>(null);

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
      {/* 옵션 시트는 비율·개수 아래에 스타일 그리드까지 담아 좁은 화면에서 화면 높이를 넘을 만큼
          길다. 높이는 SheetContent 기본값(data-[side=bottom]:h-auto)을 그대로 두고 상한만
          헤더 아래까지(보관함 시트 윗변과 같은 선)로 건다 — 내용이 짧으면 내용 높이, 길면 상한에서
          본문만 스크롤한다(SheetContent가 flex-col이라 본문의 min-h-0 flex-1이 남는 높이를 받는다).
          고정 높이를 주지 않는 것은 짧은 내용에서도 시트가 커지지 않게 하려는 것이다. */}
      <SheetContent
        side="bottom"
        className="max-h-below-header rounded-t-xl"
        // 스타일 선택 버튼으로 열었으면 고르러 온 자리(선택된 스타일, 없으면 첫 활성 스타일)로
        // 보낸다. 선택된 스타일도 비활성일 수 있어(고른 뒤 배경 재조회에서 그 스타일만 불가가 되면
        // 고른 값은 그대로 남는다) 두 선택자 모두 비활성 옵션을 거른다 — 비활성 버튼은 포커스를 받지
        // 않아, 기본 포커스를 막은 채 그쪽으로 보내면 포커스가 시트 뒤 트리거에 남는다. 대상이
        // 없으면(모델 목록 로딩 중·고를 스타일 없음) 기본 동작에 맡긴다.
        // 아이콘으로 열었으면 기본 동작(선택된 비율 칩, 본문 맨 위) 그대로다.
        onOpenAutoFocus={(event) => {
          if (entry !== "style") return;
          const body = sheetBodyRef.current;
          const section = styleSectionRef.current;
          const target =
            section?.querySelector<HTMLElement>('[role="option"][aria-selected="true"]:not(:disabled)') ??
            section?.querySelector<HTMLElement>('[role="option"]:not(:disabled)');
          if (!body || !section || !target) return;
          event.preventDefault();
          // 두 rect 의 차이라 열림 슬라이드의 transform 과 무관하다. scrollIntoView 대신 본문
          // scrollTop 을 직접 옮기는 것은 고정 위치 시트 안에서 스크롤이 잠긴 문서까지 움직일
          // 여지를 없애려는 것이다. 16px 은 본문 안쪽 여백(p-4)만큼 섹션 라벨 위를 남긴다.
          body.scrollTop +=
            section.getBoundingClientRect().top - body.getBoundingClientRect().top - 16;
          target.focus({ preventScroll: true });
        }}
        // 브라우저 실검증 — ImageStudioLibraryRail과 같은 이유. 셸의 별도 버튼이 열어서
        // SheetTrigger의 자동 포커스 복원 대상이 없다. 연 트리거로 돌려보내되, 이용 불가 화면에는
        // 스타일 선택 버튼이 없으므로 옵션 아이콘 버튼으로 물러선다.
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          (
            document.querySelector<HTMLElement>(`[data-image-studio-trigger="${entry}"]`) ??
            document.querySelector<HTMLElement>('[data-image-studio-trigger="options"]')
          )?.focus();
        }}
      >
        <SheetHeader>
          <SheetTitle>생성 옵션</SheetTitle>
        </SheetHeader>
        <div ref={sheetBodyRef} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
          <GenerateImagesOptionsFields />
          {isStyleSectionVisible && (
            <div ref={styleSectionRef}>
              <GenerateImagesStyleGrid layout="sheet" />
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
