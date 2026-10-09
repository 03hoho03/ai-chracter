import { GripVertical } from "lucide-react";
import type { ComponentProps } from "react";

type ItemDragHandleProps = Omit<ComponentProps<"button">, "type" | "className" | "children" | "onKeyDown"> & {
  /** 위치를 담은 이름(예: `2번째 엔딩 순서 변경`). */
  "aria-label": string;
  /** 위·아래 화살표 키로 한 칸 위(-1)나 아래(1)로 옮긴다(`useSortableList` 의 `handleProps`). */
  onStep?: (step: -1 | 1) => void;
};

/**
 * 접기 머리 줄 왼쪽의 순서 손잡이. dnd-kit 의 `attributes`·`listeners` 와 `useSortableList` 의 `handleProps` 를 그대로 펼쳐
 * 받는다 — 끌기 시작점과 화살표 키 재정렬을 손잡이에만 둔다(토글이나 입력칸에서 누른 화살표가 순서를 바꾸면 안 된다).
 *
 * 포커스 표시는 하우스 레시피(투명 보더 → `ring` 보더 + 50% 링)다. 50% 링만으로는 배경 대비 3:1 에 못 미친다.
 * `-ml-2` 는 아이콘을 카드 안쪽 여백 선 가까이 붙여, 손잡이가 없는 카드의 제목과 시작 위치가 크게 어긋나지 않게 한다.
 */
export function ItemDragHandle({ onStep, ...props }: ItemDragHandleProps) {
  return (
    <button
      type="button"
      {...props}
      onKeyDown={(event) => {
        if (!onStep || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
        event.preventDefault();
        onStep(event.key === "ArrowUp" ? -1 : 1);
      }}
      className="-ml-2 flex size-9 shrink-0 cursor-grab touch-none items-center justify-center rounded-lg border border-transparent text-muted-foreground outline-none hover:text-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:size-10"
    >
      <GripVertical aria-hidden className="size-4" />
    </button>
  );
}
