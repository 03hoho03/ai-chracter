import { Label } from "@ai-character-chat/ui/components/label";
import { useEffect } from "react";
import { toast } from "sonner";

import { formatMediaBookProgress, MAX_MEDIA_BOOK_CELLS, summarizeMediaBookProgress } from "@/features/build-story";

import { MediaBookAxisList } from "./MediaBookAxisList";
import { MediaBookBulkUpload } from "./MediaBookBulkUpload";
import { MEDIA_BOOK_IMAGE_UNDO_TOAST_ID, MediaBookCellPanel } from "./MediaBookCellPanel";
import { focusGridCell, MediaBookGrid } from "./MediaBookGrid";
import { useMediaBookEditor } from "../model/useMediaBookEditor";
import {
  CELL_PANEL_ID,
  PROGRESS_ID,
  resolveSelectedPosition,
  useMediaBookSelection,
} from "../model/useMediaBookSelection";

/**
 * 미디어 북 탭 — 인물 × 장면 배치표에 칸마다 그림 한 장. 위에서부터 한꺼번에 넣기 → 인물·장면 목록 → 배치표 →
 * 고른 칸의 상세 순이다. 모든 변경은 `useMediaBookEditor` 로 미디어 북 전체를 폼에 다시 쓴다. 고른 칸은 탭을 옮겨도
 * 남도록 셸 아래의 `MediaBookSelectionProvider` 가 쥔다.
 */
export function MediaBookTab() {
  const { mediaBook } = useMediaBookEditor();
  const { selected, announcement, select, selectNext, close, clearAnnouncement } = useMediaBookSelection();

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

      {hasGrid ? (
        <div className="flex flex-col gap-2">
          {/* 편집할 때마다 읽히면 시끄러워 live 영역이 아니다. "다음 미완성 칸" 이 비활성일 때 그 이유로 가리킨다. */}
          <p id={PROGRESS_ID} className="text-xs text-muted-foreground tabular-nums">
            {formatMediaBookProgress(summarizeMediaBookProgress(mediaBook))}
          </p>
          <MediaBookGrid
            mediaBook={mediaBook}
            selected={selectedPosition}
            onSelect={select}
            panelId={CELL_PANEL_ID}
          />
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-4 py-10 text-center">
          {/* 기본 경로(한 칸씩 추가)를 먼저, 파일이 이미 있는 사람의 지름길을 뒤에 둔다. 폼 열이 넓은 화면에서 줄이
              너무 길어지지 않게 문단 폭을 묶는다. */}
          <p className="max-w-md text-sm font-medium text-balance break-keep text-foreground">
            인물과 장면을 하나씩 이상 추가하면 배치표가 생겨요
          </p>
          <p className="max-w-md text-sm text-balance break-keep text-muted-foreground">
            예를 들어 인물 ‘<span className="text-foreground">유나</span>’와 장면 ‘
            <span className="text-foreground">리딩</span>’을 추가하면{" "}
            {/* 칸 이름은 가운뎃점 앞뒤에서 줄이 갈리면 두 이름으로 읽힌다. */}
            <span className="whitespace-nowrap">
              ‘<span className="text-foreground">유나 · 리딩</span>’
            </span>{" "}
            칸이 생겨요. 칸을 눌러 파일을 올리거나 생성한 이미지에서 고르면 돼요.
          </p>
          <p className="max-w-md text-sm text-balance break-keep text-muted-foreground">
            {/* 버튼 이름과 가운뎃점으로 묶은 두 낱말은 중간에서 줄이 갈리면 다른 말로 읽혀 한 덩어리로 둔다. */}
            이미지 파일이 이미 있다면 위의{" "}
            <span className="whitespace-nowrap">
              ‘<span className="text-foreground">파일 이름으로 한꺼번에 넣기</span>’로
            </span>{" "}
            <span className="whitespace-nowrap">인물·장면과</span> 칸을 한 번에 만들 수 있어요.
          </p>
        </div>
      )}

      {selectedPosition && (
        <MediaBookCellPanel
          id={CELL_PANEL_ID}
          position={selectedPosition}
          onClose={() => close(selectedPosition)}
          onReturnFocus={() => focusGridCell(selectedPosition)}
          onSelectNext={selectNext}
          progressId={PROGRESS_ID}
        />
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}
