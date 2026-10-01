import { Label } from "@ai-character-chat/ui/components/label";
import { useState } from "react";

import { MAX_MEDIA_BOOK_CELLS } from "@/features/build-story";

import { MediaBookAxisList } from "./MediaBookAxisList";
import { MediaBookBulkUpload } from "./MediaBookBulkUpload";
import { MediaBookCellPanel } from "./MediaBookCellPanel";
import { focusGridCell, MediaBookGrid, toCellKey, type MediaBookPosition } from "./MediaBookGrid";
import { useMediaBookEditor } from "../model/useMediaBookEditor";

const CELL_PANEL_ID = "media-book-cell-panel";

/**
 * 미디어 북 탭 — 인물 × 장면 배치표에 칸마다 그림 한 장. 위에서부터 한꺼번에 넣기 → 인물·장면 목록 → 배치표 →
 * 고른 칸의 상세 순이다. 모든 변경은 `useMediaBookEditor` 로 미디어 북 전체를 폼에 다시 쓴다.
 */
export function MediaBookTab() {
  const { mediaBook } = useMediaBookEditor();
  const [selected, setSelected] = useState<MediaBookPosition>();
  function handleSelect(position: MediaBookPosition, viaKeyboard: boolean) {
    setSelected(position);
    // 상세는 표 아래에 열려 좁은 화면이나 긴 표에서는 화면 밖일 수 있다. 키보드로 열면 포커스를 상세 제목으로 옮겨
    // 상세가 화면에 들어오고 다음 Tab 이 상세 안으로 간다(닫으면 그 칸으로 돌아온다). 마우스로 열면 포커스는 그대로
    // 두고 상세만 보이게 스크롤한다. 부드러운 스크롤은 쓰지 않는다(움직임을 줄이는 설정과 무관하게 순간 이동).
    requestAnimationFrame(() => {
      if (viaKeyboard) document.getElementById(`${CELL_PANEL_ID}-heading`)?.focus();
      else document.getElementById(CELL_PANEL_ID)?.scrollIntoView({ block: "nearest" });
    });
  }

  function handleClose(position: MediaBookPosition) {
    // 닫기 버튼이 사라지기 전에 포커스를 표의 그 칸으로 돌려준다.
    focusGridCell(position);
    setSelected(undefined);
  }

  const hasGrid = mediaBook.people.length > 0 && mediaBook.scenes.length > 0;
  // 고른 칸의 축이 지워졌으면 상세를 닫은 것으로 본다.
  const selectedPosition =
    selected &&
    mediaBook.people.some((person) => person.id === selected.personId) &&
    mediaBook.scenes.some((scene) => scene.id === selected.sceneId)
      ? selected
      : undefined;

  return (
    <div className="flex flex-col gap-6 py-6" data-field-path="mediaBook">
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-3">
          <Label>미디어 북</Label>
          <span className="text-xs text-muted-foreground tabular-nums" aria-label={`이미지 ${mediaBook.cells.length}장, 최대 ${MAX_MEDIA_BOOK_CELLS}장`}>
            {mediaBook.cells.length}/{MAX_MEDIA_BOOK_CELLS}
          </span>
        </div>
        <p className="text-sm break-keep text-muted-foreground">
          인물과 장면을 정하고 칸마다 그림을 한 장 넣어요. 대화 중에는 AI 가 어울리는 칸을 골라 답 아래에 보여 주고,
          칸의 표기를 시작상황·프롤로그·에필로그·등록 설명에 넣으면 그 자리에 그림이 보여요. 넣지 않아도 발행할 수 있어요.
        </p>
      </div>

      <MediaBookBulkUpload />

      <div className="grid gap-6 sm:grid-cols-2">
        <MediaBookAxisList axis="person" />
        <MediaBookAxisList axis="scene" />
      </div>

      {hasGrid ? (
        <MediaBookGrid
          mediaBook={mediaBook}
          selected={selectedPosition}
          onSelect={handleSelect}
          panelId={CELL_PANEL_ID}
        />
      ) : (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-4 py-10 text-center">
          <p className="text-sm break-keep text-muted-foreground">
            인물과 장면을 하나씩 이상 추가하면 배치표가 생겨요. 파일 이름으로 한꺼번에 넣으면 둘 다 자동으로 만들어져요.
          </p>
        </div>
      )}

      {selectedPosition && (
        <MediaBookCellPanel
          // 칸을 바꾸면 상세를 새로 그린다 — 업로드 중 표시 같은 칸별 상태가 다른 칸으로 넘어가지 않게.
          key={toCellKey(selectedPosition)}
          id={CELL_PANEL_ID}
          position={selectedPosition}
          onClose={() => handleClose(selectedPosition)}
          onReturnFocus={() => focusGridCell(selectedPosition)}
        />
      )}
    </div>
  );
}
