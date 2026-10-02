import { createContext, useContext } from "react";

import type { MediaBookValues } from "@/features/build-story";

import type { MediaBookPosition } from "../ui/MediaBookGrid";

/** 고른 칸의 상세. 표의 칸 버튼이 `aria-controls` 로 가리키므로 표와 상세가 같은 값을 쓴다. */
export const CELL_PANEL_ID = "media-book-cell-panel";
/** 상세의 제목 — 키보드로 칸을 열면 포커스가 여기로 온다. */
export const CELL_PANEL_HEADING_ID = `${CELL_PANEL_ID}-heading`;
/** 상세의 머리(썸네일·이름·표기·다음 미완성 칸) — 칸을 고르면 이 머리를 화면에 맞춘다. */
export const CELL_PANEL_HEAD_ID = `${CELL_PANEL_ID}-head`;
/** 배치표 위 진척 한 줄. "다음 미완성 칸" 이 비활성일 때 그 이유로 가리킨다. */
export const PROGRESS_ID = "media-book-progress";

export type MediaBookSelection = {
  /** 마지막으로 고른 칸. 그 뒤 축이 지워졌을 수 있으니 화면에 쓸 때는 `resolveSelectedPosition` 을 거친다. */
  selected: MediaBookPosition | undefined;
  select: (position: MediaBookPosition) => void;
  selectNext: (position: MediaBookPosition) => void;
  close: (position: MediaBookPosition) => void;
  /** 좁은 화면에서 상세를 둔 채 배치표 화면으로 돌아가 그 칸에 포커스를 둔다. */
  returnToGrid: (position: MediaBookPosition) => void;
  /** 좁은 화면에서 칸을 고르기 전에 배치표 화면을 연다. */
  openGrid: () => void;
  clearAnnouncement: () => void;
};

/** `MediaBookSelectionProvider` 가 채우는 칸 선택 컨텍스트. */
export const MediaBookSelectionContext = createContext<MediaBookSelection | undefined>(undefined);

export function useMediaBookSelection(): MediaBookSelection {
  const context = useContext(MediaBookSelectionContext);
  if (context === undefined) throw new Error("useMediaBookSelection must be used inside MediaBookSelectionProvider");
  return context;
}

/**
 * 화면에 쓸 고른 칸. 고른 칸의 인물이나 장면이 지워졌으면 상세를 닫은 것으로 본다. 표와 상세가 각자 이 함수를 같은
 * 폼 값으로 불러, 표의 선택 표시와 상세 열림이 어긋나지 않는다.
 */
export function resolveSelectedPosition(
  mediaBook: MediaBookValues,
  selected: MediaBookPosition | undefined,
): MediaBookPosition | undefined {
  if (!selected) return undefined;
  if (!mediaBook.people.some((person) => person.id === selected.personId)) return undefined;
  if (!mediaBook.scenes.some((scene) => scene.id === selected.sceneId)) return undefined;
  return selected;
}
