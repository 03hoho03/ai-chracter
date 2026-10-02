import { Label } from "@ai-character-chat/ui/components/label";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  findCell,
  formatMediaBookProgress,
  MAX_MEDIA_BOOK_CELLS,
  summarizeMediaBookProgress,
  type MediaBookCellValues,
  type MediaBookValues,
} from "@/features/build-story";

import { MediaBookAxisList } from "./MediaBookAxisList";
import { MediaBookBulkUpload } from "./MediaBookBulkUpload";
import { MEDIA_BOOK_FIRST_ACTION_SELECTOR, MEDIA_BOOK_IMAGE_UNDO_TOAST_ID, MediaBookCellPanel } from "./MediaBookCellPanel";
import {
  focusGridCell,
  MediaBookGrid,
  toCellKey,
  type MediaBookPosition,
  type MediaBookSelectMethod,
} from "./MediaBookGrid";
import { planCellSelectionScroll } from "../lib/planCellSelectionScroll";
import { useMediaBookEditor } from "../model/useMediaBookEditor";

const CELL_PANEL_ID = "media-book-cell-panel";
const PROGRESS_ID = "media-book-progress";

// 빌더 상단바(`BuilderTopBar` 의 `h-14`) 높이. 좁은 화면에서는 페이지가 그 밑으로 스크롤되고, 넓은 화면에서는 폼
// 열 창이 그 아래에서 시작하므로 어느 쪽이든 보이는 구간은 "상단바 아래 ~ 화면 바닥"이다.
const BUILDER_TOP_BAR_HEIGHT_PX = 56;
// 보이는 구간 위아래에 남길 여유. 아래는 상세 행동 줄의 `scroll-mb`(8px)와 같고, 위는 칸의 `scroll-mt` 에서 상단바를
// 뺀 값이다(좁은 화면 8px, 넓은 화면은 16px 이라 그쪽 판정이 8px 너그럽다).
const SCROLL_BREATHING_PX = 8;

/**
 * 미디어 북 탭 — 인물 × 장면 배치표에 칸마다 그림 한 장. 위에서부터 한꺼번에 넣기 → 인물·장면 목록 → 배치표 →
 * 고른 칸의 상세 순이다. 모든 변경은 `useMediaBookEditor` 로 미디어 북 전체를 폼에 다시 쓴다.
 */
export function MediaBookTab() {
  const { mediaBook } = useMediaBookEditor();
  const [selected, setSelected] = useState<MediaBookPosition>();
  const [announcement, setAnnouncement] = useState("");

  // 이미지를 바꾼 뒤의 되돌리기는 이 탭이 보이는 동안만 둔다.
  useEffect(() => () => void toast.dismiss(MEDIA_BOOK_IMAGE_UNDO_TOAST_ID), []);

  function handleSelect(position: MediaBookPosition, method: MediaBookSelectMethod) {
    const isSameCell = selected !== undefined && toCellKey(selected) === toCellKey(position);
    setSelected(position);
    // 키보드로 열면 포커스가 상세 제목으로 가 스크린리더가 제목을 읽는다 — 같은 말을 두 번 하지 않게 알림은 비운다.
    // 처음 열 때와 같은 칸을 다시 누를 때도 바뀐 것이 없어 비운다.
    setAnnouncement(method === "keyboard" || selected === undefined || isSameCell ? "" : announceCell(mediaBook, position));
    // 복사 버튼은 표기를 다른 칸에 붙이러 가는 동작이라 화면을 끌어내리지 않는다.
    if (method === "copy") return;
    // 상세는 표 아래에 열려 좁은 화면이나 긴 표에서는 화면 밖일 수 있다. 다음 프레임(상세가 그려진 뒤)에 고른 칸과
    // 상세의 첫 행동 줄이 함께 보이게, 안 되면 빈 칸은 행동 줄을 화면 바닥에, 채운 칸은 머리를 위에 맞춘다. 부드러운
    // 스크롤은 쓰지 않는다(움직임을 줄이는 설정과 무관하게 순간 이동). 키보드로 열었으면 포커스를 상세 제목으로 옮겨 다음 Tab 이 상세 안으로 간다(닫으면 그 칸으로
    // 돌아온다) — 스크롤은 위 규칙이 하므로 포커스가 화면을 다시 움직이지 않게 한다.
    requestAnimationFrame(() => {
      scrollToSelection(position, findCell(mediaBook, position.personId, position.sceneId) === undefined);
      if (method === "keyboard") document.getElementById(`${CELL_PANEL_ID}-heading`)?.focus({ preventScroll: true });
    });
  }

  function handleSelectNext(position: MediaBookPosition) {
    setSelected(position);
    setAnnouncement(announceCell(mediaBook, position));
    // 포커스는 누른 버튼에 그대로 둔다(머리는 칸이 바뀌어도 남는다). 머리가 이미 다 보이면 움직이지 않아, 마우스로
    // 연달아 누를 때 버튼이 손 밑에서 도망가지 않는다. 제목이 아니라 머리 전체를 맞추는 것은 버튼이 제목 아래 줄에
    // 있어서다 — 제목만 맞추면 버튼 줄이 화면 아래로 잘릴 수 있다.
    requestAnimationFrame(() => document.getElementById(`${CELL_PANEL_ID}-head`)?.scrollIntoView({ block: "nearest" }));
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
            onSelect={handleSelect}
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
          onClose={() => handleClose(selectedPosition)}
          onReturnFocus={() => focusGridCell(selectedPosition)}
          onSelectNext={handleSelectNext}
          progressId={PROGRESS_ID}
        />
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}

/** 마우스로 칸을 옮겼을 때 스크린리더에 들려줄 한 줄 — 상세가 다른 칸으로 바뀌었다는 것과 그 칸에 무엇이 비었는지. */
function announceCell(mediaBook: MediaBookValues, position: MediaBookPosition): string {
  const person = mediaBook.people.find((item) => item.id === position.personId);
  const scene = mediaBook.scenes.find((item) => item.id === position.sceneId);
  if (!person || !scene) return "";
  return `${person.name} · ${scene.name} 칸 — ${cellStatus(findCell(mediaBook, position.personId, position.sceneId))}`;
}

function cellStatus(cell: MediaBookCellValues | undefined): string {
  if (!cell) return "이미지 없음";
  if (cell.situationDescription.trim() === "") return "상황 설명 없음";
  return "다 채운 칸";
}

/** 고른 칸과 상세(머리와 첫 행동 줄)를 화면에 둔다. 판정은 `planCellSelectionScroll` 이 하고 여기서는 재고 움직이기만 한다. */
function scrollToSelection(position: MediaBookPosition, isEmpty: boolean) {
  const cell = document.querySelector<HTMLElement>(`[data-media-book-cell="${toCellKey(position)}"]`);
  const header = document.getElementById(`${CELL_PANEL_ID}-head`);
  const firstAction = document.querySelector<HTMLElement>(`#${CELL_PANEL_ID} ${MEDIA_BOOK_FIRST_ACTION_SELECTOR}`);
  if (!cell || !header || !firstAction) return;
  const plan = planCellSelectionScroll({
    cellTop: cell.getBoundingClientRect().top,
    firstActionBottom: firstAction.getBoundingClientRect().bottom,
    // 위아래 모두 숨 쉴 자리를 뺀다 — 위는 칸의 `scroll-mt`, 아래는 행동 줄의 `scroll-mb` 다.
    availableHeight: window.innerHeight - BUILDER_TOP_BAR_HEIGHT_PX - SCROLL_BREATHING_PX * 2,
    isEmpty,
  });
  if (plan === "both") {
    // 둘의 거리가 보이는 높이 안이므로, 행동 줄을 먼저 맞춘 뒤 칸을 맞춰도 행동 줄이 화면 밖으로 밀리지 않는다.
    firstAction.scrollIntoView({ block: "nearest" });
    cell.scrollIntoView({ block: "nearest" });
  } else if (plan === "action") {
    firstAction.scrollIntoView({ block: "end" });
  } else {
    header.scrollIntoView({ block: "start" });
  }
}
