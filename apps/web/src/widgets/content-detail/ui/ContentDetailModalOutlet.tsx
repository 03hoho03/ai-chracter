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
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogTitle className="sr-only">콘텐츠 상세정보</DialogTitle>
        {state && <ContentDetailView id={state.id} />}
      </DialogContent>
    </Dialog>
  );
}
