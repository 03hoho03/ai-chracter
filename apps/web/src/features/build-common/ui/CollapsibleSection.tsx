import { cn } from "@ai-character-chat/ui/lib/utils";
import { useId, type ReactNode } from "react";

import { useBuilderUiState, useIsItemOpen } from "../model/builderUiState";
import { CollapsibleItemToggle } from "./CollapsibleItemToggle";

type CollapsibleSectionProps = {
  openKey: string;
  /** 섹션 이름과 개수(예: `인물 3`). */
  title: string;
  /** 접혀 있어도 보이는 내용 요약(예: 이름 나열). */
  summary?: ReactNode;
  /** 열림 기록과 무관하게 펼쳐 둔다(예: 목록이 비어 새 이름 입력칸이 곧 보여야 할 때). 이때 토글은 누를 수 없게 잠긴다. */
  isAlwaysOpen?: boolean;
  children: ReactNode;
  className?: string;
};

/**
 * 목록 하나를 통째로 접는 섹션(미디어 북 인물·장면 목록). 항목 카드와 같은 토글을 쓰되 카드 껍데기 없이 제목 줄과 목록만
 * 둔다. 본문은 항목 카드와 같은 이유로 언마운트하지 않고 `hidden` 으로 숨긴다(이름 입력 초안이 남는다).
 */
export function CollapsibleSection({
  openKey,
  title,
  summary,
  isAlwaysOpen = false,
  children,
  className,
}: CollapsibleSectionProps) {
  const uiState = useBuilderUiState();
  const isStoredOpen = useIsItemOpen(openKey);
  const isOpen = isAlwaysOpen || isStoredOpen;
  const generatedId = useId();
  const ids = { title: `${generatedId}-title`, body: `${generatedId}-body` };

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {/* 접을 수 없을 때도 같은 버튼을 남기고 잠금만 건다. 다른 요소로 바꿔 그리면, 행 이름의 blur 커밋이 오류를 세우는
          바로 그 순간 Shift+Tab 으로 이 버튼에 오던 포커스가 사라진 요소와 함께 `<body>` 로 떨어진다. 높이도 그대로다. */}
      <div className="flex">
        <CollapsibleItemToggle
          openKey={openKey}
          isOpen={isOpen}
          onToggle={() => uiState.toggle(openKey)}
          titleId={ids.title}
          bodyId={ids.body}
          title={title}
          placeholderTitle={title}
          summary={summary}
          isLocked={isAlwaysOpen}
          className="-mx-2"
        />
      </div>
      <div id={ids.body} role="group" aria-labelledby={ids.title} hidden={!isOpen} className="flex flex-col gap-2">
        {children}
      </div>
    </div>
  );
}
