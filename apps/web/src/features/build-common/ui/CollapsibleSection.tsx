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
  /** 열림 기록과 무관하게 펼쳐 둔다(예: 목록이 비어 새 이름 입력칸이 곧 보여야 할 때). 이때 토글은 그리지 않고 제목만 둔다. */
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
      {isAlwaysOpen ? (
        // 접을 수 없을 때 누를 수 있는 모양을 남기면 눌러도 아무 일이 없는 버튼이 된다. 높이는 토글과 같게 맞춘다 — 첫
        // 항목이 생겨 토글로 바뀌는 순간 터치 화면에서 제목 줄이 커지며 아래 목록이 밀리지 않게.
        <p id={ids.title} className="flex min-h-9 items-center text-sm font-semibold pointer-coarse:min-h-10">
          {title}
        </p>
      ) : (
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
            className="-mx-2"
          />
        </div>
      )}
      <div id={ids.body} role="group" aria-labelledby={ids.title} hidden={!isOpen} className="flex flex-col gap-2">
        {children}
      </div>
    </div>
  );
}
