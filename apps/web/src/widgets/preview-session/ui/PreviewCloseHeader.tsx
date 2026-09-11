import type { ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ChevronLeft } from "lucide-react";

/**
 * builder-techspec.md §6 — 카드·대화 프리뷰가 함께 쓰는 헤더 크롬. 두 프리뷰가 각자 들고 있던 동일한
 * `border-b`+패딩 래퍼(`BuilderPreview.tsx`의 `CardPreview`, `PreviewSessionView.tsx`)를 여기 하나로
 * 모은다 — 대화 쪽에만 있던 [미리보기 초기화] 버튼이 `action` 슬롯으로 들어오면서 헤더 높이가 탭마다
 * 12px씩 출렁였다(사용자 피드백 1). 콘텐츠 행을 `h-8`(32px)로 고정해 `action`이 있든 없든 같은
 * 행 높이가 나오게 한다.
 *
 * **이 행 높이는 버튼 크기와 독립적이다.** `h-*`로 못박혀 있어 안의 버튼이 커져도 행 자체는
 * 출렁이지 않는다 — D-4로 버튼이 28→32px가 됐을 때 실측한 출렁임은 **0px**였다
 * (design-system-progress.md P-2 중간 상태 측정. 조사 단계는 "출렁임 재발"을 예측했으나 반증됨).
 * 그때 실제로 깨진 건 다른 문제였다: `h-7`(28px)이던 이 행 안에 32px 버튼이 들어가 위아래로
 * 2px씩 삐져나왔다(클리핑은 없었음). 그래서 `h-8`로 올렸다 — **다음에 버튼 치수가 또 바뀌어도
 * "출렁임"을 걱정할 필요는 없고, 이 행이 새 버튼 높이를 담는지만 확인하면 된다.**
 *
 * `onClose`는 lg 미만 전체화면 모드에서만 온다 — lg 이상(2단)에서는 프리뷰가 상시 노출이라 닫을
 * 대상이 아니므로 버튼만 `lg:hidden`으로 숨긴다(BuilderLayout의 다른 lg 분기와 같은 원칙: 트리에는
 * 남고 화면에만 없다). "미리보기" 라벨은 onClose 유무와 무관하게 항상 보인다.
 */
export function PreviewCloseHeader({ onClose, action }: { onClose?: () => void; action?: ReactNode }) {
  return (
    <header className="shrink-0 border-b border-border px-4 sm:px-6 py-3">
      <div className="mx-auto flex h-8 max-w-5xl items-center justify-between gap-3">
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
