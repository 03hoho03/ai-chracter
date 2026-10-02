import type { DragEvent } from "react";

import { formatMediaBookProgress, summarizeMediaBookProgress } from "@/features/build-story";
import { PreviewCloseHeader } from "@/features/build-common";

import { MediaBookGrid, type MediaBookPosition } from "./MediaBookGrid";
import { focusCellOrHeading } from "./MediaBookSelectionProvider";
import { isFileDrag } from "../lib/mediaBookImageFile";
import { useMediaBookCellImage } from "../model/useMediaBookCellImage";
import { useMediaBookEditor } from "../model/useMediaBookEditor";
import {
  CELL_PANEL_ID,
  PROGRESS_ID,
  resolveSelectedPosition,
  useMediaBookSelection,
} from "../model/useMediaBookSelection";

type MediaBookGridPaneProps = {
  /** lg 미만에서 이 화면을 닫고 폼으로 돌아간다. 닫기 버튼은 lg 이상에서 숨는다. */
  onClose: () => void;
};

/**
 * 미디어 북 탭일 때 미리보기 열에 서는 배치표 묶음 — 진척 한 줄과 배치표(인물·장면이 없으면 빈 상태). lg 이상에서는
 * 폼 열의 칸 상세와 나란히, lg 미만에서는 상단 버튼으로 여는 미리보기 화면 그 자체라 한 벌이 두 폭을 맡는다(두 벌이면
 * 칸 버튼을 찾는 선택자가 숨은 쪽을 잡는다). 면은 깔지 않는다 — 열의 `background` 그대로여야 sticky 장면 열의
 * `bg-background` 가 열 면과 같고 채운 칸 웰 `bg-muted` 가 사라지지 않는다.
 */
export function MediaBookGridPane({ onClose }: MediaBookGridPaneProps) {
  const { mediaBook } = useMediaBookEditor();
  const { selected, select } = useMediaBookSelection();
  const { uploadImage, applyImage } = useMediaBookCellImage(focusCellOrHeading);
  const hasGrid = mediaBook.people.length > 0 && mediaBook.scenes.length > 0;

  /**
   * 칸에 끌어다 놓은 이미지 — 칸 상세의 "파일 올리기" 와 같은 길로 올려 넣고(채운 칸이면 같은 되돌리기), 넣은 칸을 골라
   * 상세에 띄운다. 올리는 동안 사용자가 무엇이든 누르거나 입력했으면 고르지 않는다 — 그 사이 고른 다른 칸이나 쓰던 글을
   * 업로드가 끝나는 순간 빼앗지 않게. 칸에는 그대로 들어가 표에서 보인다. 포커스가 옮겨 갔는지로는 가를 수 없다 — 칸을
   * 고르면 포커스가 늘 같은 상세 제목으로 가서, 올리는 동안 다른 칸을 골라도 포커스 요소는 그대로다.
   */
  async function handleDropImage(position: MediaBookPosition, file: File) {
    let hasInteracted = false;
    const markInteracted = () => {
      hasInteracted = true;
    };
    document.addEventListener("pointerdown", markInteracted, true);
    document.addEventListener("keydown", markInteracted, true);
    try {
      const image = await uploadImage(file);
      if (!image || !applyImage(position, image)) return;
      if (!hasInteracted) select(position);
    } finally {
      document.removeEventListener("pointerdown", markInteracted, true);
      document.removeEventListener("keydown", markInteracted, true);
    }
  }

  /**
   * 칸이 아닌 자리(칸 사이 틈·이름 머리·진척 줄·빈 상태)에 파일을 놓으면 브라우저가 그 파일을 새 화면으로 열어 쓰던
   * 빌더를 떠난다. 이 묶음 안에서는 "놓을 수 없음" 으로 받아 막는다. 칸이 이미 받은 끌기(기본 동작을 막았다)는 건드리지
   * 않는다 — 여기서 덮으면 칸 위에서도 놓을 수 없게 된다.
   */
  function handlePaneDrag(event: DragEvent<HTMLElement>) {
    if (event.defaultPrevented || !isFileDrag(event.dataTransfer.types)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "none";
  }

  return (
    // 높이를 스스로 정하는 이유는 대화·카드 미리보기와 같다 — lg 미만에서는 조상에 정해진 높이가 없다. `relative` 는
    // 표의 화면 밖 제목(`sr-only` caption)의 기준을 이 묶음으로 묶는다. 없으면 그 요소가 문서 맨 위 기준으로 자리를
    // 잡아 넓은 화면에서 열이 아니라 문서가 세로로 스크롤된다.
    <section
      aria-label="배치표"
      className="relative flex h-below-header flex-col"
      onDragOver={handlePaneDrag}
      onDrop={handlePaneDrag}
    >
      <PreviewCloseHeader title="배치표" onClose={onClose} />
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-4 sm:px-6 py-4">
        {hasGrid ? (
          <>
            {/* 편집할 때마다 읽히면 시끄러워 live 영역이 아니다. "다음 미완성 칸" 이 비활성일 때 그 이유로 가리킨다. */}
            <p id={PROGRESS_ID} className="text-xs break-keep text-muted-foreground tabular-nums">
              {formatMediaBookProgress(summarizeMediaBookProgress(mediaBook))}
            </p>
            <MediaBookGrid
              mediaBook={mediaBook}
              selected={resolveSelectedPosition(mediaBook, selected)}
              onSelect={select}
              onDropImage={handleDropImage}
              panelId={CELL_PANEL_ID}
            />
          </>
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-4 py-10 text-center">
            {/* 기본 경로(한 칸씩 추가)를 먼저, 파일이 이미 있는 사람의 지름길을 뒤에 둔다. 열이 넓을 때 줄이 너무
                길어지지 않게 문단 폭을 묶는다. */}
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
              {/* 버튼 이름과 가운뎃점으로 묶은 두 낱말은 중간에서 줄이 갈리면 다른 말로 읽혀 한 덩어리로 둔다. 그
                  버튼은 다른 열(좁은 화면에서는 다른 화면)에 있어 "위의" 같은 방향어를 붙이지 않는다. */}
              이미지 파일이 이미 있다면{" "}
              <span className="whitespace-nowrap">
                ‘<span className="text-foreground">파일 이름으로 한꺼번에 넣기</span>’로
              </span>{" "}
              <span className="whitespace-nowrap">인물·장면과</span> 칸을 한 번에 만들 수 있어요.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
