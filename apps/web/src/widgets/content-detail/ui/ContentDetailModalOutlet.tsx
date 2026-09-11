import { Dialog, DialogContent, DialogTitle } from "@ai-character-chat/ui/components/dialog";

import { useContentDetailModal } from "@/shared/lib/content-detail-modal/useContentDetailModal";

import { ContentDetailView } from "./ContentDetailView";

/**
 * techspec-content-detail.md §1 — `routes/__root.tsx`에 `<Outlet />`과 함께 한 번만 마운트된다.
 * ✕ 버튼/바깥 클릭/ESC는 모두 Radix Dialog의 `onOpenChange(false)`로 수렴하므로 세 방식을 각각
 * 구현할 필요가 없다. 아래 사용중인 리스트(홈, 프로필)는 언마운트되지 않으므로 스크롤 위치도
 * 그대로 유지된다.
 */
export function ContentDetailModalOutlet() {
  const { state, close } = useContentDetailModal();

  return (
    <Dialog open={state !== null} onOpenChange={(open) => !open && close()}>
      {/* design-system-progress.md P-5(D-11) — flex-col로 바꿔 `ContentDetailView`가 내놓는
          [스크롤 본문(flex-1 overflow-y-auto), 플레이 CTA(shrink-0)] 두 아이템을 그대로 받는다.
          overflow-y-auto는 여기서 본문 쪽으로 옮겨갔다(CTA는 스크롤에 딸려가면 안 된다). */}
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg">
        <DialogTitle className="sr-only">콘텐츠 상세정보</DialogTitle>
        {state && <ContentDetailView id={state.id} variant="modal" />}
      </DialogContent>
    </Dialog>
  );
}
