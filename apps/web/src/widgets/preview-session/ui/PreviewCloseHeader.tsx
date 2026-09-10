import { Button } from "@ai-character-chat/ui/components/button";
import { ChevronLeft } from "lucide-react";

/**
 * builder-techspec.md §6 — 카드·대화 프리뷰가 함께 쓰는 닫기 크롬. 두 프리뷰가 각자 들고 있던 동일한
 * 마크업을 여기 하나로 모은다(`BuilderPreview.tsx`의 `CardPreview`, `PreviewSessionView.tsx`가 호출).
 *
 * `onClose`는 lg 미만 전체화면 모드에서만 온다 — lg 이상(2단)에서는 프리뷰가 상시 노출이라 닫을
 * 대상이 아니므로 버튼만 `lg:hidden`으로 숨긴다(BuilderLayout의 다른 lg 분기와 같은 원칙: 트리에는
 * 남고 화면에만 없다). "미리보기" 라벨은 onClose 유무와 무관하게 항상 보인다.
 */
export function PreviewCloseHeader({ onClose }: { onClose?: () => void }) {
  return (
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
  );
}
