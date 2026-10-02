import { Label } from "@ai-character-chat/ui/components/label";
import { useEffect } from "react";
import { toast } from "sonner";

import { MAX_MEDIA_BOOK_CELLS } from "@/features/build-story";

import { MediaBookAxisList } from "./MediaBookAxisList";
import { MediaBookBulkUpload } from "./MediaBookBulkUpload";
import { MEDIA_BOOK_IMAGE_UNDO_TOAST_ID, MediaBookCellPanel } from "./MediaBookCellPanel";
import { focusGridCell } from "./MediaBookGrid";
import { useMediaBookEditor } from "../model/useMediaBookEditor";
import {
  CELL_PANEL_ID,
  PROGRESS_ID,
  resolveSelectedPosition,
  useMediaBookSelection,
} from "../model/useMediaBookSelection";

/**
 * 미디어 북 탭 — 인물 × 장면 배치표에 칸마다 그림 한 장. 폼 열에는 위에서부터 한꺼번에 넣기 → 인물·장면 목록 → 고른
 * 칸의 상세가 서고, 배치표는 미리보기 열(좁은 화면에서는 미리보기 화면, `MediaBookGridPane`)에 선다. 모든 변경은
 * `useMediaBookEditor` 로 미디어 북 전체를 폼에 다시 쓴다. 고른 칸은 두 열이 함께 보고 탭을 옮겨도 남도록 셸 아래의
 * `MediaBookSelectionProvider` 가 쥔다.
 */
export function MediaBookTab() {
  const { mediaBook } = useMediaBookEditor();
  const { selected, announcement, selectNext, close, clearAnnouncement } = useMediaBookSelection();

  // 이미지를 바꾼 뒤의 되돌리기는 이 탭이 보이는 동안만 둔다. 알림도 탭을 떠날 때 비워, 돌아왔을 때 지난 문장이
  // 남아 있지 않게 한다.
  useEffect(
    () => () => {
      toast.dismiss(MEDIA_BOOK_IMAGE_UNDO_TOAST_ID);
      clearAnnouncement();
    },
    [clearAnnouncement],
  );

  const hasGrid = mediaBook.people.length > 0 && mediaBook.scenes.length > 0;
  const selectedPosition = resolveSelectedPosition(mediaBook, selected);

  return (
    // `relative` 는 화면 밖 글자(`sr-only` 알림·파일 입력)의 기준을 이 탭으로 묶는다. 없으면 그 요소들이 문서 맨 위
    // 기준으로 자리를 잡아, 넓은 화면에서 폼 열이 아니라 문서가 세로로 스크롤되고 칸을 고를 때 창이 밀려 폼 열 위쪽이
    // 상단바 밑으로 들어간다.
    <div className="relative flex flex-col gap-6 py-6" data-field-path="mediaBook">
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-3">
          <Label>미디어 북</Label>
          <span className="text-xs text-muted-foreground tabular-nums" aria-label={`이미지 ${mediaBook.cells.length}장, 최대 ${MAX_MEDIA_BOOK_CELLS}장`}>
            {mediaBook.cells.length}/{MAX_MEDIA_BOOK_CELLS}
          </span>
        </div>
        <p className="text-sm break-keep text-muted-foreground">
          인물과 장면이 만나는 칸마다 이미지를 한 장씩 넣으면, 대화 중에 AI가 어울리는 이미지를 골라 답 아래에 보여
          줘요. 넣지 않아도 발행할 수 있어요.
        </p>
      </div>

      <MediaBookBulkUpload />

      <div className="grid gap-6 sm:grid-cols-2">
        <MediaBookAxisList axis="person" />
        <MediaBookAxisList axis="scene" />
      </div>

      {selectedPosition ? (
        <MediaBookCellPanel
          id={CELL_PANEL_ID}
          position={selectedPosition}
          onClose={() => close(selectedPosition)}
          onReturnFocus={() => focusGridCell(selectedPosition)}
          onSelectNext={selectNext}
          progressId={PROGRESS_ID}
        />
      ) : (
        hasGrid && <CellPanelPlaceholder />
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}

/**
 * 칸을 고르기 전 상세 자리. 상세와 같은 윤곽이라 칸을 고르면 같은 자리에서 내용만 바뀐다. 점선이 아닌 것은 비어 있는
 * 상태가 아니라 상세가 열릴 자리여서다.
 */
function CellPanelPlaceholder() {
  return (
    <div className="rounded-xl border border-border p-4">
      <p className="text-sm break-keep text-muted-foreground">
        <span className="hidden lg:inline">오른쪽 </span>배치표에서 칸을 고르면 여기에서 이미지를 넣고 상황 설명을 적을 수
        있어요.
      </p>
    </div>
  );
}
