import {
  PointerSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type ScreenReaderInstructions,
} from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";

import { dragMoveIndices, nextAnnouncement, orderAfterMove, stepMove } from "../model/listMove";

/** 손잡이 DOM id. 정렬 id(필드 배열의 렌더 키나 항목 값의 id)는 문서 안에서 겹치지 않으므로 목록 이름을 넣지 않는다. */
export function sortableHandleId(sortableId: string): string {
  return `sortable-handle-${sortableId}`;
}

/** `ItemDragHandle` 에 `attributes`·`listeners` 뒤로 펼쳐 넣는 손잡이 속성. */
export type SortableHandleProps = {
  id: string;
  "aria-roledescription": string;
  onStep: (step: -1 | 1) => void;
};

type SortableListOptions = {
  /** dnd-kit 정렬 id — 지금 목록 순서대로. */
  ids: readonly string[];
  move: (from: number, to: number) => void;
  /** 손잡이에 포커스가 오면 읽히는 안내의 목적어(조사까지, 예: `노트를`). */
  itemObject: string;
  /** 안내 뒤에 잇는, 이 목록에서 순서가 무슨 뜻인지(예: `위에 있을수록 먼저 실려요.`). */
  orderMeaning: string;
  /**
   * 옮긴 뒤 읽힐 문장. `orderAfter` 는 옮긴 뒤의 정렬 id 순서다. 없으면 `N번째로 옮겼어요.`(목록 전체에서의 자리) — 손잡이 이름을
   * 종류별 순번으로 짓는 목록(규칙과 규칙 그룹이 섞인 목록)은 같은 순번으로 말하도록 넘긴다.
   */
  movedMessage?: (orderAfter: readonly string[], movedId: string) => string;
};

function defaultMovedMessage(orderAfter: readonly string[], movedId: string): string {
  return `${orderAfter.indexOf(movedId) + 1}번째로 옮겼어요.`;
}

/**
 * 끌어서 정렬하는 반복 항목 목록의 공용부. 끌기는 포인터로만 하고, 키보드는 손잡이에서 위·아래 화살표로 한 칸씩 옮긴다.
 *
 * dnd-kit 의 키보드 센서(Space 로 집고 화살표로 옮기고 다시 Space)를 쓰지 않는 이유: 한 번 누를 때마다 순서가 바뀌는 편이
 * 단계가 적고, 센서의 기본 안내는 영어라 어차피 한국어로 다시 써야 한다. 그래서 dnd-kit 의 안내도 이 방식으로 바꿔 준다
 * (`accessibility`). 화살표 이동은 끌기가 아니라서 dnd-kit 의 위치 전환이 걸리지 않고 즉시 바뀐다(실측: 옮긴 뒤 여러
 * 프레임 동안 카드의 transform 없음·전환 0s) — 그래서 움직임 줄이기 설정에 따로 맞출 것이 없다.
 *
 * 화살표로 옮긴 뒤 포커스는 옮긴 항목의 손잡이에 남는다 — 거듭 누른 화살표가 같은 항목을 계속 옮기고, "N번째로 옮겼어요"
 * 안내가 그 항목의 새 자리를 말한다. 옮긴 손잡이는 렌더가 끝난 뒤에야 제자리에 있으므로 포커스는 커밋 뒤 effect 에서 준다.
 *
 * 화살표 이동의 안내는 `announcement` 로 돌려준다 — 호출부가 `aria-live="polite"` 영역에 그린다(같은 영역을 삭제 안내 등에도
 * 쓸 수 있게 `announce` 도 준다). 같은 문장이 연달아 와도 다시 읽힌다(`nextAnnouncement`). 끌기 안내는 dnd-kit 이 자기 영역에서
 * 읽는다.
 */
export function useSortableList({
  ids,
  move,
  itemObject,
  orderMeaning,
  movedMessage = defaultMovedMessage,
}: SortableListOptions) {
  const sensors = useSensors(useSensor(PointerSensor));
  const [announcement, setAnnouncement] = useState("");
  const announce = (message: string) => setAnnouncement((previous) => nextAnnouncement(previous, message));
  // 재정렬 뒤 포커스를 둘 손잡이. 렌더가 끝난 뒤에야 그 요소가 제자리에 있으므로 effect 에서 옮긴다.
  const pendingFocusIdRef = useRef<string | undefined>(undefined);

  // 목록이 바뀌는 렌더마다 돈다 — 목록 값이 필드 배열이든 호출부가 넘긴 배열이든 이동 뒤 커밋을 놓치지 않게 의존성을 두지 않는다.
  useEffect(() => {
    const targetId = pendingFocusIdRef.current;
    if (!targetId) return;
    pendingFocusIdRef.current = undefined;
    document.getElementById(targetId)?.focus();
  });

  function step(index: number, direction: -1 | 1) {
    const moved = stepMove(ids, index, direction);
    if (!moved) return;
    move(moved.from, moved.to);
    pendingFocusIdRef.current = sortableHandleId(moved.movedId);
    announce(movedMessage(orderAfterMove(ids, moved), moved.movedId));
  }

  function handleDragEnd({ active, over }: DragEndEvent) {
    const indices = dragMoveIndices(ids, String(active.id), over ? String(over.id) : null);
    if (indices) move(indices.from, indices.to);
  }

  const announcements: Announcements = {
    onDragStart: () => undefined,
    onDragOver: () => undefined,
    onDragCancel: () => "옮기기를 취소했어요.",
    onDragEnd: ({ active, over }) => {
      const indices = dragMoveIndices(ids, String(active.id), over ? String(over.id) : null);
      return indices ? movedMessage(orderAfterMove(ids, indices), String(active.id)) : undefined;
    },
  };
  const screenReaderInstructions: ScreenReaderInstructions = {
    draggable: `위·아래 화살표 키로 ${itemObject} 한 칸씩 옮길 수 있어요. ${orderMeaning}`,
  };

  return {
    sensors,
    accessibility: { announcements, screenReaderInstructions },
    handleDragEnd,
    /** `index` 번째 항목의 손잡이 속성. */
    handleProps(index: number): SortableHandleProps {
      return {
        id: sortableHandleId(ids[index] ?? ""),
        "aria-roledescription": "순서 핸들",
        onStep: (direction) => step(index, direction),
      };
    },
    announcement,
    announce,
  };
}
