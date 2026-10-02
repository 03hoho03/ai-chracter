import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useFormContext } from "react-hook-form";

import {
  findCell,
  type MediaBookCellValues,
  type MediaBookValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { MEDIA_BOOK_FIRST_ACTION_SELECTOR } from "./MediaBookCellPanel";
import { focusGridCell, toCellKey, type MediaBookPosition, type MediaBookSelectMethod } from "./MediaBookGrid";
import { planCellSelectionScroll } from "../lib/planCellSelectionScroll";
import {
  CELL_PANEL_HEAD_ID,
  CELL_PANEL_HEADING_ID,
  CELL_PANEL_ID,
  MediaBookSelectionContext,
  type MediaBookSelection,
} from "../model/useMediaBookSelection";

// 빌더 상단바(`BuilderTopBar` 의 `h-14`) 높이. 좁은 화면에서는 페이지가 그 밑으로 스크롤되고, 넓은 화면에서는 폼
// 열 창이 그 아래에서 시작하므로 어느 쪽이든 보이는 구간은 "상단바 아래 ~ 화면 바닥"이다.
const BUILDER_TOP_BAR_HEIGHT_PX = 56;
// 보이는 구간 위아래에 남길 여유. 아래는 상세 행동 줄의 `scroll-mb`(8px)와 같고, 위는 칸의 `scroll-mt` 에서 상단바를
// 뺀 값이다(좁은 화면 8px, 넓은 화면은 16px 이라 그쪽 판정이 8px 너그럽다).
const SCROLL_BREATHING_PX = 8;

type MediaBookSelectionProviderProps = {
  children: ReactNode;
};

/**
 * 미디어 북의 고른 칸과 그 알림을 쥐고, 칸 고르기·다음 칸·닫기 동작을 내려 준다. 표와 상세가 서로 다른 열에 있어도
 * 같은 선택을 보도록 셸이 두 열을 함께 감싼다. 셸이 아니라 이 컴포넌트가 상태를 쥐는 이유는 칸을 고를 때 셸과 미리보기
 * 전체가 다시 그려지지 않고 이 컨텍스트를 읽는 쪽만 다시 그려지게 하려는 것이다. 폼은 구독하지 않고 동작하는 순간의
 * 값만 읽는다.
 */
export function MediaBookSelectionProvider({ children }: MediaBookSelectionProviderProps) {
  const { getValues } = useFormContext<StoryBuilderFormValues>();
  const [selected, setSelected] = useState<MediaBookPosition>();
  const [announcement, setAnnouncement] = useState("");

  const clearAnnouncement = useCallback(() => setAnnouncement(""), []);

  const value = useMemo<MediaBookSelection>(() => {
    function select(position: MediaBookPosition, method: MediaBookSelectMethod) {
      const mediaBook = getValues("mediaBook");
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
        if (method === "keyboard") document.getElementById(CELL_PANEL_HEADING_ID)?.focus({ preventScroll: true });
      });
    }

    function selectNext(position: MediaBookPosition) {
      setSelected(position);
      setAnnouncement(announceCell(getValues("mediaBook"), position));
      // 포커스는 누른 버튼에 그대로 둔다(머리는 칸이 바뀌어도 남는다). 머리가 이미 다 보이면 움직이지 않아, 마우스로
      // 연달아 누를 때 버튼이 손 밑에서 도망가지 않는다. 제목이 아니라 머리 전체를 맞추는 것은 버튼이 제목 아래 줄에
      // 있어서다 — 제목만 맞추면 버튼 줄이 화면 아래로 잘릴 수 있다.
      requestAnimationFrame(() => document.getElementById(CELL_PANEL_HEAD_ID)?.scrollIntoView({ block: "nearest" }));
    }

    function close(position: MediaBookPosition) {
      // 닫기 버튼이 사라지기 전에 포커스를 표의 그 칸으로 돌려준다.
      focusGridCell(position);
      setSelected(undefined);
    }

    return { selected, announcement, select, selectNext, close, clearAnnouncement };
  }, [selected, announcement, getValues, clearAnnouncement]);

  return <MediaBookSelectionContext.Provider value={value}>{children}</MediaBookSelectionContext.Provider>;
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
  const header = document.getElementById(CELL_PANEL_HEAD_ID);
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
