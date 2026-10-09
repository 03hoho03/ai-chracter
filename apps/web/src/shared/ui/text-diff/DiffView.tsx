import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown } from "lucide-react";
import { useId, useMemo, useState, type ReactNode } from "react";

import { buildDiffView, type DiffBlock, type DiffSegment } from "@/shared/lib/text-diff/buildDiffView";

type DiffViewProps = {
  /** 바꾸기 전 글(옛 판·버전 때 글). */
  before: string;
  /** 바꾼 뒤 글(새 판·지금 글). */
  after: string;
  /** 차이가 너무 커서 비교를 못 할 때 안내 아래에 둘 것 — 두 글을 따로 여는 버튼 같은. */
  tooLargeAction?: ReactNode;
  className?: string;
};

/**
 * 두 글의 차이. 더한 글자는 `ring` 밑줄, 지운 글자는 `destructive` 틴트 위 취소선이다 — 강조는 `ring`, 잃은 것은
 * `destructive` 틴트라는 색 규칙 그대로이고, 솔리드 채움을 하나도 더하지 않는다. 조각마다 화면에 보이지 않는
 * "추가:"/"삭제:"를 앞에 붙여 색과 선만으로 뜻을 싣지 않는다(보조기기·색 구분이 어려운 이용자).
 *
 * 바뀌지 않은 문단 묶음은 "바뀌지 않은 문단 n개" 버튼으로 접혀 있다 — 5천 자 글에서 한 문단을 고친 판도 그 문단만
 * 바로 보이게. 글자는 그대로이고 문단 나눔만 바뀐 문단은 표시할 조각이 없어 그 사실을 한 줄로 말한다.
 *
 * 이 컴포넌트는 `diff` 를 끌어오므로 정적으로 가져오지 않는다 — `LazyDiffView` 로만 닿는다(소설 판 이력 모달이
 * 앱 루트에 늘 마운트돼 있어, 정적으로 가져오면 비교 라이브러리가 첫 화면 번들에 실린다).
 */
export function DiffView({ before, after, tooLargeAction, className }: DiffViewProps) {
  // 비교는 수백 ms 까지 걸릴 수 있어(시간 상한 둘의 합) 같은 두 글이면 다시 하지 않는다.
  const view = useMemo(() => buildDiffView(before, after), [before, after]);

  if (view.status === "tooLarge") {
    return (
      <div className={cn("flex flex-col items-start gap-2", className)}>
        <p className="text-sm break-keep text-muted-foreground">
          차이가 너무 커서 비교할 수 없어요. 두 글을 따로 열어 보세요.
        </p>
        {tooLargeAction}
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {view.granularity === "sentence" && (
        <p className="text-xs break-keep text-muted-foreground">글이 많이 달라 문장 단위로 비교했어요.</p>
      )}
      {view.changedParagraphCount === 0 ? (
        <p className="text-sm break-keep text-muted-foreground">바뀐 곳이 없어요.</p>
      ) : (
        <p className="text-xs break-keep text-muted-foreground tabular-nums">바뀐 문단 {view.changedParagraphCount}개</p>
      )}
      <div className="flex flex-col gap-3 text-sm leading-relaxed break-keep text-foreground">
        {view.blocks.map((block, index) => (
          // 비교 결과는 두 글이 같으면 바뀌지 않아 순서가 곧 정체성이다.
          <DiffBlockView key={index} block={block} />
        ))}
      </div>
    </div>
  );
}

function DiffBlockView({ block }: { block: DiffBlock }) {
  if (block.kind === "unchanged") return <UnchangedParagraphs paragraphs={block.paragraphs} />;
  if (block.whitespaceOnly) {
    return (
      <div className="flex flex-col gap-1">
        <p className="whitespace-pre-line">{block.segments.map((segment) => segment.text).join("")}</p>
        <p className="text-xs text-muted-foreground">문단 나눔만 바뀌었어요.</p>
      </div>
    );
  }
  return (
    <p className="whitespace-pre-line">
      {block.segments.map((segment, index) => (
        <DiffSegmentView key={index} segment={segment} />
      ))}
    </p>
  );
}

function DiffSegmentView({ segment }: { segment: DiffSegment }) {
  switch (segment.kind) {
    case "added":
      return (
        <ins className="text-foreground underline decoration-ring decoration-2 underline-offset-4">
          <span className="sr-only">추가: </span>
          {segment.text}
        </ins>
      );
    case "removed":
      return (
        <del className="rounded-sm bg-destructive/10 text-destructive-text line-through">
          <span className="sr-only">삭제: </span>
          {segment.text}
        </del>
      );
    default:
      return <span>{segment.text}</span>;
  }
}

/** 바뀌지 않은 문단 묶음. 접혀 있고, 펼치면 그 자리에 문단이 그대로 놓인다. hover 면은 `secondary` 반투명 — 이
 * 컴포넌트는 모달 표면(`popover`) 위에 놓이는데 `muted` 는 그 표면과 값이 같아 사라진다. */
function UnchangedParagraphs({ paragraphs }: { paragraphs: string[] }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const panelId = useId();

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={panelId}
        className="-mx-2 flex min-h-11 items-center gap-1.5 self-start rounded-md px-2 text-xs text-muted-foreground outline-none motion-safe:transition-colors hover:bg-secondary/50 focus-visible:ring-3 focus-visible:ring-ring/50"
        onClick={() => setIsExpanded((open) => !open)}
      >
        <ChevronDown aria-hidden className={cn("size-4 motion-safe:transition-transform", isExpanded && "rotate-180")} />
        바뀌지 않은 문단 {paragraphs.length}개
      </button>
      {isExpanded && (
        <div id={panelId} className="flex flex-col gap-3 text-muted-foreground">
          {paragraphs.map((paragraph, index) => (
            <p key={index} className="whitespace-pre-line">
              {paragraph}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
