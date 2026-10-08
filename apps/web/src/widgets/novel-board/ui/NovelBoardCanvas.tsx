import "./novelBoard.css";

import { Button } from "@ai-character-chat/ui/components/button";
import {
  Background,
  BackgroundVariant,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  useStore,
  type AriaLabelConfig,
  type Edge,
  type NodeChange,
  type OnMoveEnd,
} from "@xyflow/react";
import { useAtomValue } from "jotai";
import { Maximize, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

import type { NovelBoardLayout } from "@/entities/novel";
import { themeAtom } from "@/shared/model/theme";

import type { BoardModel, BoardNode } from "../model/boardNode";
import { nodeKeyToSelection } from "../model/boardSelection";
import { pickSelectedNodeKey, toCardEscapeAction } from "../model/canvasSelection";
import { isRectInView, toInitialFitNodeIds } from "../model/boardViewport";
import { fitBatchFrames } from "../model/fitBatchFrames";
import { buildCharacterEdges, layoutBoard } from "../model/layoutBoard";
import { mergeLocalNodes } from "../model/mergeLocalNodes";
import { useBoardLayoutSave } from "../model/useBoardLayoutSave";

import { BOARD_NODE_TYPES } from "./BoardNodes";

/** 화가 이보다 많으면 화면 밖 카드를 그리지 않는다. 그 아래에서는 전부 그리는 쪽이 팬할 때 카드가 늦게 나타나지 않는다. */
const RENDER_VISIBLE_ONLY_EPISODE_COUNT = 100;
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 1.5;

/** 선은 고를 것이 없다(정보는 카드에 있다) — 눌러도 고르기 변경을 내지 않게. */
const DEFAULT_EDGE_OPTIONS = { selectable: false };

const DIRECTION_LABEL: Record<string, string> = { up: "위로", down: "아래로", left: "왼쪽으로", right: "오른쪽으로" };

// 라이브러리 기본 안내는 영어이고 "지우기 키로 지운다"를 말한다 — 이 보드는 지우기 키를 꺼 두어 거짓 안내가 된다.
// 키보드를 켠 노드 안내는 라이브러리가 `keyboardDisabled` 키에서 읽어 두 키에 같은 문장을 둔다.
const NODE_DESCRIPTION =
  "엔터나 스페이스로 카드를 고르면 패널에서 고쳐요. 고른 카드는 화살표 키로 옮기고, Shift 와 함께 누르면 더 멀리 옮겨요. 카드를 옮겨도 화 순서는 바뀌지 않아요.";
const ARIA_LABEL_CONFIG: Partial<AriaLabelConfig> = {
  "node.a11yDescription.default": NODE_DESCRIPTION,
  "node.a11yDescription.keyboardDisabled": NODE_DESCRIPTION,
  "node.a11yDescription.ariaLiveMessage": ({ direction }) => `카드를 ${DIRECTION_LABEL[direction] ?? ""} 옮겼어요.`,
  "edge.a11yDescription.default": "선은 화 순서와 인물이 나온 화를 보여 줘요.",
};

type NovelBoardCanvasProps = {
  novelId: string;
  model: BoardModel;
  /** 받은 배치. 저장한 적 없거나 받지 못했으면 `null` — 자동 배치로 그린다. */
  savedLayout: NovelBoardLayout | null;
  /** 상세 `limits.boardLayoutMaxBytes`. */
  maxBytes: number;
  /** 주소가 고른 노드. 캔버스는 고른 것을 들고 있지 않고 이 값을 그린다. */
  selectedNodeKey: string | undefined;
  /** 카드를 고르거나(노드 키) 고르기를 풀 때(`undefined`). 호출부가 주소를 옮긴다 — 고치던 글이 있으면 확인을 거쳐
   * 그만둘 수도 있다. */
  onSelectNode: (nodeKey: string | undefined) => void;
};

/**
 * 편집 보드의 캔버스(`@xyflow/react`). 넓은 화면에서만 마운트되고, 이 모듈은 지연 로딩이라 좁은 화면은 캔버스
 * 라이브러리를 내려받지 않는다(`LazyNovelBoardCanvas`).
 *
 * - **노드 자리**: 서버 데이터 → `layoutBoard` 로 계산하고, 화면의 자리는 로컬 상태로 든다. 서버 데이터가 다시 오면 다시
 *   계산하되 화면이 옮긴 자리를 잇는다(`mergeLocalNodes`). 카드를 놓을 때(끌기 끝과 키보드 이동 — 키보드 이동은 끌기
 *   끝 콜백을 부르지 않고 `dragging: false` 위치 변경만 보낸다)와 화면 이동이 끝날 때 1초 디바운스로 저장한다.
 * - **고르기**: 주소가 정한다. 라이브러리가 보내는 고르기 변경은 적용하지 않고 호출부에 넘겨 주소를 옮긴다 — 고치던
 *   글을 버릴지 확인을 거쳐야 하고, 고르기의 출처가 둘이 되지 않게. 끌기만으로는 고르지 않고, 고르기를 푸는 길은 빈
 *   곳 클릭과 고른 카드의 Esc 뿐이다.
 * - **인물 선**: 고르거나 키보드 포커스가 있는 인물 하나만 그린다(모든 인물의 선을 늘 그리면 읽을 수 없다). hover 로는
 *   그리지 않는다 — 포인터가 지날 때마다 선이 번쩍인다.
 * - 연결·선 바꾸기·지우기 키·여러 개 고르기는 끈다. 이야기 순서는 서버가 정하고 카드는 그 순서를 바꾸지 않는다.
 * - 스크롤은 줌이 아니라 팬이다(세로로 긴 한 열이라서). 줌은 핀치·Ctrl+스크롤과 왼쪽 아래 버튼.
 */
export function NovelBoardCanvas(props: NovelBoardCanvasProps) {
  return (
    <ReactFlowProvider>
      <BoardFlow {...props} />
    </ReactFlowProvider>
  );
}

function BoardFlow({ novelId, model, savedLayout, maxBytes, selectedNodeKey, onSelectNode }: NovelBoardCanvasProps) {
  const theme = useAtomValue(themeAtom);
  const reactFlow = useReactFlow<BoardNode, Edge>();
  const canvasWidth = useStore((state) => state.width);
  const canvasHeight = useStore((state) => state.height);
  const computed = useMemo(() => layoutBoard(model, savedLayout), [model, savedLayout]);
  // 처음 화면은 마운트 때 한 번 정한다 — 저장할 때마다 받은 배치 캐시가 바뀌어도 화면을 다시 맞추지 않는다.
  const [initialViewport] = useState(() => savedLayout?.viewport ?? null);
  const [initialFitNodes] = useState(() => toInitialFitNodeIds(computed.nodes, model));
  const [flow, setFlow] = useState(() => ({ source: computed.nodes, nodes: computed.nodes }));
  const [focusedNodeKey, setFocusedNodeKey] = useState<string | undefined>(undefined);
  // 캔버스 안에서 고른 카드. 그 카드는 이미 보이는 자리라 화면을 옮기지 않는다(아래 효과).
  const canvasSelectedKeyRef = useRef<string | undefined>(undefined);

  // 서버 데이터가 바뀌어 새로 계산했으면 렌더 중에 화면 자리를 이어 붙인다 — 효과에서 하면 옛 노드로 한 번 그린 뒤
  // 바뀐다.
  let nodes = flow.nodes;
  if (flow.source !== computed.nodes) {
    nodes = mergeLocalNodes(computed.nodes, flow.nodes, model);
    setFlow({ source: computed.nodes, nodes });
  }

  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const modelRef = useRef(model);
  modelRef.current = model;
  const save = useBoardLayoutSave({
    novelId,
    maxBytes,
    read: () => ({ nodes: nodesRef.current, viewport: reactFlow.getViewport() }),
  });

  const displayNodes = useMemo(
    () =>
      nodes.map((node): BoardNode => {
        if (node.type === "batchFrame") return node;
        const isSelected = node.id === selectedNodeKey;
        return {
          ...node,
          selected: isSelected,
          className: "group outline-none",
          ariaLabel: toNodeAriaLabel(node),
          // 역할 설명은 라이브러리가 늘 영어 "node" 를 달아 한국어로 덮는다.
          domAttributes: isSelected
            ? { "aria-roledescription": "카드", "aria-current": "true" }
            : { "aria-roledescription": "카드" },
        };
      }),
    [nodes, selectedNodeKey],
  );

  const edgeCharacterId = toCharacterId(focusedNodeKey) ?? toCharacterId(selectedNodeKey);
  const edges = useMemo(
    () => [
      ...computed.edges,
      ...buildCharacterEdges(edgeCharacterId, model).map((edge) => ({ ...edge, className: "novel-board-appears-edge" })),
    ],
    [computed.edges, edgeCharacterId, model],
  );

  /** 카드가 화면 안에 통째로 보이지 않으면 그 카드로 순간 이동한다(배율은 그대로). */
  function revealNode(nodeKey: string) {
    const node = reactFlow.getNode(nodeKey);
    if (node === undefined) return;
    const width = node.measured?.width ?? 0;
    const height = node.measured?.height ?? 0;
    const viewport = reactFlow.getViewport();
    if (isRectInView({ ...node.position, width, height }, viewport, { width: canvasWidth, height: canvasHeight })) return;
    void reactFlow.setCenter(node.position.x + width / 2, node.position.y + height / 2, {
      zoom: viewport.zoom,
      duration: 0,
    });
  }

  // 캔버스 밖에서 고른 카드(목록 링크·뒤로 가기·새 화 완성)가 화면 밖이면 그 카드로 순간 이동한다. 캔버스 안에서 고른
  // 카드는 이미 보이는 자리라 옮기지 않고, 그 표시는 한 번 쓰고 비운다 — 남겨 두면 나중에 밖에서 같은 카드를 다시
  // 골랐을 때 옮기지 않는다.
  useEffect(() => {
    if (selectedNodeKey === undefined) return;
    if (selectedNodeKey === canvasSelectedKeyRef.current) {
      canvasSelectedKeyRef.current = undefined;
      return;
    }
    revealNode(selectedNodeKey);
    // 옮길 시점은 고른 카드가 바뀐 순간이다.
  }, [selectedNodeKey]);

  function handleNodesChange(changes: NodeChange<BoardNode>[]) {
    const placement = changes.filter((change) => change.type === "position" || change.type === "dimensions");
    if (placement.length > 0) {
      setFlow((prev) => ({
        source: prev.source,
        nodes: fitBatchFrames(applyNodeChanges(placement, prev.nodes), modelRef.current),
      }));
    }
    if (changes.some((change) => change.type === "position" && change.dragging === false)) save.schedule();

    // 고르기만 따른다. 푸는 길은 빈 곳 클릭과 고른 카드의 Esc 뿐이다(`pickSelectedNodeKey`).
    const picked = pickSelectedNodeKey(changes);
    if (picked === undefined || picked === selectedNodeKey) return;
    canvasSelectedKeyRef.current = picked;
    onSelectNode(picked);
  }

  function handlePaneClick() {
    if (selectedNodeKey !== undefined) onSelectNode(undefined);
  }

  // 카드의 Esc 는 라이브러리보다 먼저 받는다 — 라이브러리는 고르지 않은 카드의 Esc 를 "고르기"로 처리한다.
  function handleKeyDownCapture(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") return;
    const nodeKey = nodeKeyOf(event.target);
    if (nodeKey === undefined || !(event.target instanceof Element) || !event.target.matches(".react-flow__node")) return;
    event.stopPropagation();
    if (toCardEscapeAction(nodeKey, selectedNodeKey) === "deselect") onSelectNode(undefined);
  }

  // 화면 이동이 끝나면 저장한다. 이용자가 움직인 것만 — 처음 맞추기·고른 카드로 옮기기처럼 화면이 스스로 옮긴 것은
  // 사건(event)이 없다.
  const handleMoveEnd: OnMoveEnd = (event) => {
    if (event !== null) save.schedule();
  };

  // 키보드로 카드를 돌 때, 라이브러리는 카드가 조금이라도 보이면 화면을 옮기지 않아 상단 바 쪽에 걸린 카드의 포커스
  // 링이 가려진다. 통째로 보이지 않으면 그 카드로 옮긴다(포인터로 누른 포커스는 옮기지 않는다).
  function handleFocus(event: FocusEvent<HTMLDivElement>) {
    const nodeKey = nodeKeyOf(event.target);
    setFocusedNodeKey(nodeKey);
    if (nodeKey !== undefined && event.target instanceof Element && event.target.matches(":focus-visible")) {
      revealNode(nodeKey);
    }
  }

  function zoomBy(direction: "in" | "out") {
    void (direction === "in" ? reactFlow.zoomIn({ duration: 0 }) : reactFlow.zoomOut({ duration: 0 }));
    save.schedule();
  }

  return (
    <ReactFlow<BoardNode, Edge>
      aria-label="카드 보드"
      nodes={displayNodes}
      edges={edges}
      nodeTypes={BOARD_NODE_TYPES}
      onNodesChange={handleNodesChange}
      onPaneClick={handlePaneClick}
      onKeyDownCapture={handleKeyDownCapture}
      defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
      onMoveEnd={handleMoveEnd}
      onFocus={handleFocus}
      onBlur={() => setFocusedNodeKey(undefined)}
      colorMode={theme}
      ariaLabelConfig={ARIA_LABEL_CONFIG}
      nodesConnectable={false}
      edgesReconnectable={false}
      edgesFocusable={false}
      nodesFocusable
      elementsSelectable
      selectNodesOnDrag={false}
      deleteKeyCode={null}
      selectionKeyCode={null}
      multiSelectionKeyCode={null}
      zoomOnDoubleClick={false}
      zoomOnScroll={false}
      panOnScroll
      minZoom={MIN_ZOOM}
      maxZoom={MAX_ZOOM}
      onlyRenderVisibleElements={model.episodes.length > RENDER_VISIBLE_ONLY_EPISODE_COUNT}
      {...(initialViewport === null
        ? { fitView: true, fitViewOptions: { nodes: initialFitNodes, maxZoom: 1, duration: 0 } }
        : { defaultViewport: initialViewport })}
    >
      <Background variant={BackgroundVariant.Dots} gap={24} />
      <Panel position="bottom-left" className="flex gap-1.5">
        <Button type="button" variant="outline" size="icon-sm" aria-label="확대" onClick={() => zoomBy("in")}>
          <Plus aria-hidden />
        </Button>
        <Button type="button" variant="outline" size="icon-sm" aria-label="축소" onClick={() => zoomBy("out")}>
          <Minus aria-hidden />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label="화면 맞춤"
          onClick={() => {
            void reactFlow.fitView({ duration: 0, maxZoom: 1 });
            save.schedule();
          }}
        >
          <Maximize aria-hidden />
        </Button>
      </Panel>
    </ReactFlow>
  );
}

/** 포커스가 들어간 노드의 키. 노드 상자(`.react-flow__node`)가 `data-id` 로 키를 단다. */
function nodeKeyOf(target: EventTarget): string | undefined {
  if (!(target instanceof Element)) return undefined;
  return target.closest(".react-flow__node")?.getAttribute("data-id") ?? undefined;
}

function toCharacterId(nodeKey: string | undefined): string | undefined {
  if (nodeKey === undefined) return undefined;
  const selection = nodeKeyToSelection(nodeKey);
  return selection?.kind === "character" ? selection.id : undefined;
}

/** 노드 상자(`role="group"`)의 이름. 상자는 내용에서 이름을 계산하지 않아 따로 준다. */
function toNodeAriaLabel(node: Exclude<BoardNode, { type: "batchFrame" }>): string {
  switch (node.type) {
    case "episode":
      return node.data.title === null ? `${node.data.ordinal}화` : `${node.data.ordinal}화. ${node.data.title}`;
    case "character":
      return `인물 ${node.data.name}`;
    case "notes":
      return "설정 노트";
  }
}
