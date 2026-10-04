import { Dialog, DialogContent, DialogTitle } from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import type { ReactNode } from "react";

import { useContentDetailModal } from "@/entities/content";

import { ContentDetailView } from "./ContentDetailView";
import { useContentEditingViewport } from "../lib/useContentEditingViewport";

/**
 * `routes/__root.tsx`에 `<Outlet />`과 함께 한 번만 마운트된다.
 * ✕ 버튼/바깥 클릭/ESC는 모두 Radix Dialog의 `onOpenChange(false)`로 수렴하므로 세 방식을 각각
 * 구현할 필요가 없다. 아래 사용중인 리스트(홈, 프로필)는 언마운트되지 않으므로 스크롤 위치도
 * 그대로 유지된다.
 */
export function ContentDetailModalOutlet({ renderComments }: { renderComments: (id: string) => ReactNode }) {
  const { state, close } = useContentDetailModal();
  const editingViewport = useContentEditingViewport();

  return (
    <Dialog open={state !== undefined} onOpenChange={(open) => !open && close()}>
      {/* `ContentDetailView`가 내놓는 [헤더, 스크롤 본문(`DialogBody`), 플레이 바]를 받는다. `DialogBody`가 있으면
          이 상자가 스스로 flex 컬럼이 되므로 여기서는 높이 상한만 바꾼다 — 프리미티브 기본 상한
          (`max-h-dialog`)이 같은 변형 선택자로 걸려 있어 평범한 `max-h-*`로는 이기지 못한다. 편집 중에는
          아래 inline `maxHeight`가 이 클래스를 덮고, `data-editing`이 헤더 제목을 한 줄로 줄인다. */}
      {/* 스토리는 2열 레이아웃이 필요해 더 넓게(`sm:max-w-2xl`),
          캐릭터는 지금 폭(`sm:max-w-lg`)을 그대로 유지한다. */}
      <DialogContent
        className={cn("sm:max-w-lg has-data-[slot=dialog-body]:max-h-[85vh]", state?.type === "story" && "sm:max-w-2xl")}
        data-content-detail
        data-editing={editingViewport ? "" : undefined}
        style={editingViewport ? { top: editingViewport.top + editingViewport.height / 2, maxHeight: Math.max(120, editingViewport.height - 24) } : undefined}
      >
        {/* 열려 있는 동안은 `ContentDetailView`가 모든 상태에서 제목을 하나 낸다. 여기 제목은 닫힘 애니메이션
            중(`state`가 먼저 비어 뷰가 언마운트된 뒤)에만 다이얼로그 이름을 지킨다 — 둘이 함께 있으면 제목 id가
            겹쳐 앞쪽인 이 문구가 다이얼로그 이름이 된다. */}
        {!state && <DialogTitle className="sr-only">콘텐츠 상세정보</DialogTitle>}
        {state && <ContentDetailView key={state.id} id={state.id} type={state.type} variant="modal" comments={renderComments(state.id)} />}
      </DialogContent>
    </Dialog>
  );
}
