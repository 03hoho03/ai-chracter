import { cn } from "@ai-character-chat/ui/lib/utils";
import { Handle, Position, type NodeProps, type NodeTypes } from "@xyflow/react";
import { memo } from "react";

import {
  APPEARS_SOURCE_HANDLE,
  APPEARS_TARGET_HANDLE,
  NEXT_SOURCE_HANDLE,
  NEXT_TARGET_HANDLE,
  type BatchFrameNode,
  type CharacterNode,
  type EpisodeNode,
  type NotesNode,
} from "../model/boardNode";

import { CharacterCardBody, EpisodeCardBody, NotesCardBody, boardCardClassName } from "./BoardCardBodies";

// 캔버스 노드 넷. 카드 크기는 배치 계산의 크기 상수와 같아야 묶음 테두리·인물 레인이 카드와 겹치지 않는다
// (화 240×120, 인물 200×88, 노트 200×120). 키보드 포커스는 라이브러리가 카드를 감싼 노드 상자에 두므로 링은 그 상자의
// `group` 을 따라 그린다(상자에 `group` 클래스를 캔버스가 붙인다). 카드 안에 버튼을 두지 않는다 — 카드 자체가 고르는
// 단위이고, 동작은 전부 옆 패널에 있다.
//
// 선 끝점(`Handle`)은 연결용 손잡이가 아니라 선이 꽂히는 자리다. 화 카드에는 들어오는 선이 둘이라(위: 앞 화,
// 오른쪽: 인물) 자리마다 id 를 나눈다.

const FOCUS_RING = "group-focus-visible:ring-3 group-focus-visible:ring-ring/50";

const EpisodeCardNode = memo(function EpisodeCardNode({ data, selected }: NodeProps<EpisodeNode>) {
  return (
    <div className={cn(boardCardClassName({ isSelected: selected }), FOCUS_RING, "h-30 w-60")}>
      <Handle type="target" position={Position.Top} id={NEXT_TARGET_HANDLE} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} id={NEXT_SOURCE_HANDLE} isConnectable={false} />
      <Handle type="target" position={Position.Right} id={APPEARS_TARGET_HANDLE} isConnectable={false} />
      <EpisodeCardBody data={data} />
    </div>
  );
});

const CharacterCardNode = memo(function CharacterCardNode({ data, selected }: NodeProps<CharacterNode>) {
  return (
    <div className={cn(boardCardClassName({ isSelected: selected }), FOCUS_RING, "h-22 w-50")}>
      <Handle type="source" position={Position.Left} id={APPEARS_SOURCE_HANDLE} isConnectable={false} />
      <CharacterCardBody data={data} />
    </div>
  );
});

const NotesCardNode = memo(function NotesCardNode({ data, selected }: NodeProps<NotesNode>) {
  return (
    <div
      className={cn(boardCardClassName({ isSelected: selected, isDashed: data.notes.trim() === "" }), FOCUS_RING, "h-30 w-50")}
    >
      <NotesCardBody data={data} />
    </div>
  );
});

/** 묶음 테두리 — 한 번에 만든 화들을 두른 배경. 끌거나 고를 수 없고 채움이 없다(투명) — 화 사이 선이 그 위로
 * 보이고, 바탕 위에 면을 한 겹 더 쌓지 않는다. 머리 줄은 테두리 위쪽 여백 안에 둔다. */
const BatchFrameCardNode = memo(function BatchFrameCardNode({ data }: NodeProps<BatchFrameNode>) {
  return (
    <div aria-hidden className="size-full rounded-2xl border border-border px-4 pt-1.5">
      <p className="text-xs text-muted-foreground tabular-nums">
        묶음 {data.ordinal}
        {data.rangeLabel !== undefined && ` · ${data.rangeLabel}`}
      </p>
    </div>
  );
});

/** 노드 종류 → 컴포넌트. 모듈 상수여야 한다 — 렌더마다 새 객체면 라이브러리가 노드를 전부 다시 마운트한다. */
export const BOARD_NODE_TYPES = {
  episode: EpisodeCardNode,
  character: CharacterCardNode,
  notes: NotesCardNode,
  batchFrame: BatchFrameCardNode,
} satisfies NodeTypes;
