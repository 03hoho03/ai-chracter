import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { ITEM_TOGGLE_ATTRIBUTE } from "../lib/focusItemToggle";

type CollapsibleItemToggleProps = {
  openKey: string;
  isOpen: boolean;
  onToggle: () => void;
  titleId: string;
  bodyId: string;
  /** 읽기 전용 제목. 비어 있으면(공백뿐 포함) `placeholderTitle` 을 흐린 글자로 보인다. */
  title: string | undefined;
  placeholderTitle: string;
  /** 화면에는 안 보이고 제목 앞에 읽히는 말(예: `3번째 노트: `). 같은 이름 항목이 여럿일 때 가르는 데 쓴다. */
  srTitlePrefix?: string;
  /** 제목 오른쪽의 보조 정보. 한 줄로 잘린다. */
  summary?: ReactNode;
  hasError?: boolean;
  /** 지금은 접을 수 없다(늘 펼침). 버튼은 그대로 두고 누를 수 없음만 알린다 — 요소를 바꾸면 그 위의 포커스가 사라진다. */
  isLocked?: boolean;
  className?: string;
};

/**
 * 접기 머리 줄의 토글 버튼 — 제목·요약·오류 표시·셰브런을 하나의 버튼에 담는다. 삭제 버튼과 손잡이는 이 버튼 안이 아니라
 * 형제로 둔다. 버튼 안에 버튼을 넣는 것은 무효 HTML 이고, 넣더라도 안쪽 버튼의 클릭(포인터·Enter·Space 모두 클릭을
 * 낸다)이 토글까지 올라가 함께 눌린다.
 *
 * 펼침·접힘은 즉시 바뀐다. 본문을 `hidden` 으로 숨겨 높이 전이를 걸 수 없고, 어두운 방에서 갑작스러운 움직임은 놀람이라
 * 셰브런 회전에도 전이를 두지 않는다.
 *
 * 포커스 표시는 하우스 레시피다 — 50% 링만으로는 배경 대비 3:1 에 못 미쳐 투명 보더를 `ring` 색으로 바꾸는 1px 이 그
 * 몫을 진다. 터치 화면에서는 손가락으로 누를 수 있게 높이를 40px 로 올린다.
 *
 * hover 면은 `secondary` 다. 이 토글이 앉는 면(항목 카드·규칙 그룹·미디어 북 섹션)은 모두 `background` 인데, 그 위에서
 * `muted` 는 다크 1.0946 / 라이트 1.0902:1 로 거의 보이지 않았다. 채움 위의 흐린 글자(요약·자리표시 제목)는 라이트에서 `secondary` 위 AA 에 못
 * 미쳐 hover 동안 `foreground` 로 올린다.
 */
export function CollapsibleItemToggle({
  openKey,
  isOpen,
  onToggle,
  titleId,
  bodyId,
  title,
  placeholderTitle,
  srTitlePrefix,
  summary,
  hasError = false,
  isLocked = false,
  className,
}: CollapsibleItemToggleProps) {
  const trimmedTitle = title?.trim();

  return (
    <button
      type="button"
      {...{ [ITEM_TOGGLE_ATTRIBUTE]: openKey }}
      aria-expanded={isOpen}
      aria-controls={bodyId}
      // `disabled` 를 쓰지 않는다 — 붙는 순간 브라우저가 포커스를 빼 `<body>` 로 떨어진다.
      aria-disabled={isLocked || undefined}
      onClick={isLocked ? undefined : onToggle}
      className={cn(
        "group flex min-h-9 min-w-0 flex-1 items-center gap-2 rounded-lg border border-transparent px-2 text-left outline-none select-none first:-ml-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10",
        !isLocked && "hover:bg-secondary",
        className,
      )}
    >
      <span id={titleId} className="min-w-0 truncate text-sm font-semibold">
        {srTitlePrefix && <span className="sr-only">{srTitlePrefix}</span>}
        {trimmedTitle ? (
          trimmedTitle
        ) : (
          <span className={cn("font-medium text-muted-foreground", !isLocked && "group-hover:text-foreground")}>
            {placeholderTitle}
          </span>
        )}
      </span>
      {/* 요약은 남는 폭만 쓴다(기준 폭 0) — 좁아지면 제목보다 요약이 먼저 잘린다. */}
      <span
        className={cn(
          "min-w-0 flex-1 basis-0 truncate text-xs text-muted-foreground",
          !isLocked && "group-hover:text-foreground",
        )}
      >
        {summary}
      </span>
      {hasError && (
        <>
          <TriangleAlert aria-hidden className="size-3.5 shrink-0 text-destructive-text" />
          <span className="sr-only"> (입력 오류가 있어요)</span>
        </>
      )}
      {!isLocked && (
        <ChevronDown aria-hidden className={cn("size-4 shrink-0 text-muted-foreground", isOpen && "rotate-180")} />
      )}
    </button>
  );
}
