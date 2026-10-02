import { useCallback, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { flushSync } from "react-dom";
import { useFormContext } from "react-hook-form";

import {
  findCell,
  type MediaBookCellValues,
  type MediaBookValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { toCellKey, type MediaBookPosition, type MediaBookSelectMethod } from "./MediaBookGrid";
import {
  CELL_PANEL_HEAD_ID,
  CELL_PANEL_HEADING_ID,
  MediaBookSelectionContext,
  type MediaBookSelection,
} from "../model/useMediaBookSelection";

type MediaBookSelectionProviderProps = {
  children: ReactNode;
  /** 셸의 lg 미만 미리보기 화면(미디어 북 탭에서는 배치표) 열림 상태를 바꾼다. lg 이상에서는 레이아웃이 이 값을 무시한다. */
  setPreviewOpen: Dispatch<SetStateAction<boolean>>;
};

/**
 * 미디어 북의 고른 칸과 그 알림을 쥐고, 칸 고르기·다음 칸·닫기 동작을 내려 준다. 표와 상세가 서로 다른 열에 있어도
 * 같은 선택을 보도록 셸이 두 열을 함께 감싼다. 셸이 아니라 이 컴포넌트가 상태를 쥐는 이유는 칸을 고를 때 셸과 미리보기
 * 전체가 다시 그려지지 않고 이 컨텍스트를 읽는 쪽만 다시 그려지게 하려는 것이다. 폼은 구독하지 않고 동작하는 순간의
 * 값만 읽는다.
 */
export function MediaBookSelectionProvider({ children, setPreviewOpen }: MediaBookSelectionProviderProps) {
  const { getValues } = useFormContext<StoryBuilderFormValues>();
  const [selected, setSelected] = useState<MediaBookPosition>();
  const [announcement, setAnnouncement] = useState("");

  const clearAnnouncement = useCallback(() => setAnnouncement(""), []);

  const value = useMemo<MediaBookSelection>(() => {
    function select(position: MediaBookPosition, method: MediaBookSelectMethod) {
      const isSameCell = selected !== undefined && toCellKey(selected) === toCellKey(position);
      // 처음 열 때와 같은 칸을 다시 누를 때는 바뀐 것이 없어 알리지 않는다.
      const nextAnnouncement =
        selected === undefined || isSameCell ? "" : announceCell(getValues("mediaBook"), position);
      setSelected(position);
      // 복사 버튼은 표기를 다른 칸에 붙이러 가는 동작이라 화면을 움직이지 않는다(좁은 화면에서도 배치표에 머문다).
      if (method === "copy") {
        setAnnouncement(nextAnnouncement);
        return;
      }
      // 좁은 화면에서는 배치표 화면을 닫고 폼 열의 상세로 넘어간다. 누른 칸이 화면에서 사라지므로 아래에서 포커스가
      // 상세 제목으로 간다.
      setPreviewOpen(false);
      // 다음 프레임(상세가 그려진 뒤)에 상세 머리를 화면 맨 위에 맞춘다. 표는 다른 열에 그대로 보이므로 상세를 위에서부터
      // 보여 주면 되고, 연달아 다른 칸을 고르면 머리가 이미 위라 움직이지 않는다. 부드러운 스크롤은 쓰지 않는다(움직임을
      // 줄이는 설정과 무관하게 순간 이동). 키보드로 열었거나 누른 칸이 화면에서 사라졌으면 포커스를 상세 제목으로 옮겨
      // 다음 Tab 이 상세 안으로 가게 하고(닫으면 그 칸으로 돌아온다), 스크린리더가 제목을 읽으므로 알림은 비운다.
      requestAnimationFrame(() => {
        document.getElementById(CELL_PANEL_HEAD_ID)?.scrollIntoView({ block: "start" });
        const shouldFocusHeading = method === "keyboard" || findVisibleCell(position) === undefined;
        if (shouldFocusHeading) focusHeading();
        setAnnouncement(shouldFocusHeading ? "" : nextAnnouncement);
      });
    }

    function selectNext(position: MediaBookPosition) {
      setSelected(position);
      setAnnouncement(announceCell(getValues("mediaBook"), position));
      // 포커스는 누른 버튼에 그대로 둔다(머리는 칸이 바뀌어도 남는다). 머리가 이미 다 보이면 움직이지 않아, 마우스로
      // 연달아 누를 때 버튼이 손 밑에서 도망가지 않는다. 제목이 아니라 머리 전체를 맞추는 것은 버튼이 제목 아래 줄에
      // 있어서다 — 제목만 맞추면 버튼 줄이 화면 아래로 잘릴 수 있다. 표가 옆 열에 보이면 새 칸도 그 열 안에 들어오게
      // 한다 — 긴 표에서는 새 칸이 열 밖에 있을 수 있다.
      requestAnimationFrame(() => {
        document.getElementById(CELL_PANEL_HEAD_ID)?.scrollIntoView({ block: "nearest" });
        findVisibleCell(position)?.scrollIntoView({ block: "nearest", inline: "nearest" });
      });
    }

    function close(position: MediaBookPosition) {
      const cell = findVisibleCell(position);
      if (cell) {
        // 닫기 버튼이 사라지기 전에 포커스를 표의 그 칸으로 돌려준다.
        cell.focus();
        setSelected(undefined);
        return;
      }
      // 표가 다른 화면이면(좁은 화면) 폼에 남아, 같은 자리에 서는 자리표시의 "배치표에서 칸 고르기" 로 보낸다. 그
      // 버튼은 선택을 비운 뒤에야 생기므로 화면을 먼저 바꾸고 곧바로 옮긴다 — 닫기 버튼이 사라진 채 포커스가 body 로
      // 떨어진 틈이 남지 않게.
      flushSync(() => setSelected(undefined));
      document.querySelector<HTMLElement>(OPEN_GRID_SELECTOR)?.focus();
    }

    function returnToGrid(position: MediaBookPosition) {
      // 좁은 화면에서 상세를 둔 채 배치표 화면으로 돌아가 그 칸에 포커스를 둔다(선택은 남아 표에 테두리가 보인다). 누른
      // 버튼은 폼과 함께 숨으므로 화면을 먼저 바꾸고 곧바로 옮긴다. 배치표 화면이 숨어 있던 동안의 스크롤 위치에 기대지
      // 않고 매번 그 칸을 화면에 들인다.
      flushSync(() => setPreviewOpen(true));
      const cell = findVisibleCell(position);
      cell?.focus({ preventScroll: true });
      cell?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    function openGrid() {
      // 좁은 화면에서 자리표시의 버튼으로 배치표 화면을 연다. 누른 버튼이 폼과 함께 숨으므로 표의 첫 칸으로 포커스를 옮긴다.
      flushSync(() => setPreviewOpen(true));
      document.querySelector<HTMLElement>("[data-media-book-cell]")?.focus();
    }

    return { selected, announcement, select, selectNext, close, returnToGrid, openGrid, clearAnnouncement };
  }, [selected, announcement, getValues, clearAnnouncement, setPreviewOpen]);

  return <MediaBookSelectionContext.Provider value={value}>{children}</MediaBookSelectionContext.Provider>;
}

/** 좁은 화면의 상세 자리표시에 있는 "배치표에서 칸 고르기" 버튼. 상세를 닫으면 포커스가 여기로 온다. */
const OPEN_GRID_SELECTOR = "[data-media-book-open-grid]";

/**
 * 상세 안에서 누른 버튼이 사라졌을 때(비우기 확인 뒤, 되돌리기 토스트) 포커스를 둘 곳. 표의 그 칸이 보이면 그 칸,
 * 아니면(좁은 화면에서 표가 다른 화면이면) 그대로 남는 상세 제목이다 — 보이지 않는 칸에 포커스를 주면 body 로
 * 떨어진다. 칸이 보이는지는 화면 폭이 아니라 그 버튼이 실제로 그려졌는지로 판정한다.
 */
export function focusCellOrHeading(position: MediaBookPosition, options?: FocusOptions) {
  const cell = findVisibleCell(position);
  if (cell) cell.focus(options);
  else focusHeading();
}

/** 표의 그 칸 버튼 — 화면에 보일 때만. 좁은 화면에서 배치표 화면을 닫으면 칸은 DOM 에 남아도 보이지 않는다. */
function findVisibleCell(position: MediaBookPosition): HTMLButtonElement | undefined {
  const cell = document.querySelector<HTMLButtonElement>(`[data-media-book-cell="${toCellKey(position)}"]`);
  return cell && cell.getClientRects().length > 0 ? cell : undefined;
}

function focusHeading() {
  document.getElementById(CELL_PANEL_HEADING_ID)?.focus({ preventScroll: true });
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
