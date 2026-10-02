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
  /** 목록이 비었다. 접을 것이 없으니 토글 대신 제목 글자만 두고 펼쳐 둔다(새 이름 입력칸이 곧 첫 길이다). */
  isEmpty?: boolean;
  /** 항목은 있지만 지금은 접을 수 없다(예: 저장하지 못한 이름이 남았을 때). 열림 기록과 무관하게 펼치고 토글을 잠근다. */
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
  isEmpty = false,
  isAlwaysOpen = false,
  children,
  className,
}: CollapsibleSectionProps) {
  const uiState = useBuilderUiState();
  const isStoredOpen = useIsItemOpen(openKey);
  const isOpen = isEmpty || isAlwaysOpen || isStoredOpen;
  const generatedId = useId();
  const ids = { title: `${generatedId}-title`, body: `${generatedId}-body` };

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {isEmpty ? (
        // 빈 목록의 제목은 누를 것이 없으니 버튼이 아니다 — 버튼으로 두면 쓸모없는 Tab 정지점이 되고 스크린리더는 "펼침,
        // 사용할 수 없음 버튼"으로 읽는다. 이 머리 줄 위에 포커스가 있는 채로 비는 길은 없다(마지막 항목은 지우기 버튼으로만
        // 지우고, 지우면 포커스가 새 이름 입력칸으로 간다). 높이·글자 위치는 토글과 같게 맞춘다.
        <p
          id={ids.title}
          className="-mx-2 flex min-h-9 items-center border border-transparent px-2 text-sm font-semibold pointer-coarse:min-h-10"
        >
          {title}
        </p>
      ) : (
        // 항목이 있는 동안에는 접을 수 없어도 같은 버튼을 남기고 잠금만 건다. 다른 요소로 바꿔 그리면, 행 이름의 blur
        // 커밋이 오류를 세우는 바로 그 순간 Shift+Tab 으로 이 버튼에 오던 포커스가 사라진 요소와 함께 `<body>` 로 떨어진다.
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
      )}
      <div id={ids.body} role="group" aria-labelledby={ids.title} hidden={!isOpen} className="flex flex-col gap-2">
        {children}
      </div>
    </div>
  );
}
