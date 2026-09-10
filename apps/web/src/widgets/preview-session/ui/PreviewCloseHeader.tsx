import type { ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ChevronLeft } from "lucide-react";

/**
 * builder-techspec.md §6 — 카드·대화 프리뷰가 함께 쓰는 헤더 크롬. 두 프리뷰가 각자 들고 있던 동일한
 * `border-b`+패딩 래퍼(`BuilderPreview.tsx`의 `CardPreview`, `PreviewSessionView.tsx`)를 여기 하나로
 * 모은다 — 대화 쪽에만 있던 [미리보기 초기화] 버튼이 `action` 슬롯으로 들어오면서 헤더 높이가 탭마다
 * 12px씩 출렁였다(사용자 피드백 1). 콘텐츠 행을 `h-7`(28px)로 고정해 `action`이 있든 없든 같은
 * 행 높이가 나오게 한다 — 대화 쪽 [초기화] 버튼(size="sm"=28px)이 이미 그 높이를 요구했으므로,
 * 카드 쪽도 같은 높이로 맞추는 쪽이 자연스럽다(반대로 대화 쪽 버튼을 줄이면 클릭 타깃이 작아진다).
 *
 * `onClose`는 lg 미만 전체화면 모드에서만 온다 — lg 이상(2단)에서는 프리뷰가 상시 노출이라 닫을
 * 대상이 아니므로 버튼만 `lg:hidden`으로 숨긴다(BuilderLayout의 다른 lg 분기와 같은 원칙: 트리에는
 * 남고 화면에만 없다). "미리보기" 라벨은 onClose 유무와 무관하게 항상 보인다.
 */
export function PreviewCloseHeader({ onClose, action }: { onClose?: () => void; action?: ReactNode }) {
  return (
    <header className="shrink-0 border-b border-border px-4 sm:px-6 py-3">
      <div className="mx-auto flex h-7 max-w-5xl items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {onClose && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="미리보기 닫기"
              onClick={onClose}
              className="lg:hidden"
            >
              <ChevronLeft aria-hidden className="size-4" />
            </Button>
          )}
          <span className="text-sm font-semibold text-foreground">미리보기</span>
        </div>
        {action}
      </div>
    </header>
  );
}
