import { cn } from "@ai-character-chat/ui/lib/utils";
import { useId, type CSSProperties, type ReactNode, type Ref } from "react";

import { useBuilderUiState, useIsItemOpen } from "../model/builderUiState";
import { CollapsibleItemToggle } from "./CollapsibleItemToggle";

type CollapsibleItemCardProps = {
  /** 열림 키(`itemOpenKey`·`indexOpenKey`). 열림 여부는 셸의 화면 상태에서 읽는다. */
  openKey: string;
  title: string | undefined;
  /** 제목이 비었을 때 보일 말(예: `새 스탯`). */
  placeholderTitle: string;
  srTitlePrefix?: string;
  summary?: ReactNode;
  /** 머리 줄 오류 표시. 펼침과는 따로다 — 오류 항목을 여는 일은 발행 실패 경로가 저장소에 기록한다. */
  hasError?: boolean;
  /** 토글 앞에 둘 것(순서 손잡이). */
  leading?: ReactNode;
  /** 토글 뒤에 둘 것(삭제 버튼). */
  trailing?: ReactNode;
  /** 제목 노드 id. 바깥 목록 항목이 `aria-labelledby` 로 가리켜야 할 때만 넘긴다. */
  titleId?: string;
  /** 펼친 본문. 접혀도 언마운트하지 않는다. */
  children: ReactNode;
  /** 순서 변경 목록이 카드 루트에 거는 ref·style(끌 때 카드 전체가 움직인다). */
  ref?: Ref<HTMLDivElement>;
  style?: CSSProperties;
  className?: string;
};

/**
 * 빌더 반복 항목 카드. 머리 줄(손잡이 · 토글 · 삭제)은 접힘·펼침 어느 쪽이든 같은 자리·같은 모양이고 상세는 그 아래로
 * 펼쳐진다.
 *
 * 접힌 본문은 언마운트하지 않고 `hidden` 으로 숨긴다. 언마운트하면 폼 등록·마운트 집합이 펼친 적 있는 항목에 따라 갈려
 * 자동저장 본문이 달라질 수 있고(값이 비어 있던 필드는 처음 붙을 때 빈 문자열이 써진다), 쓰다 만 칩 입력·업로드 미리보기
 * 같은 항목 안 state 가 접을 때마다 사라진다. 본문과 카드에 `overflow-hidden` 을 두지 않는다 — 본문 안 피커 패널·
 * 선택 목록이 잘린다.
 *
 * 본문은 제목을 이름으로 하는 `group` 이다. 항목마다 `region` 을 두면 목록이 길 때 랜드마크가 수십 개가 된다.
 */
export function CollapsibleItemCard({
  openKey,
  title,
  placeholderTitle,
  srTitlePrefix,
  summary,
  hasError,
  leading,
  trailing,
  titleId,
  children,
  ref,
  style,
  className,
}: CollapsibleItemCardProps) {
  const uiState = useBuilderUiState();
  const isOpen = useIsItemOpen(openKey);
  const generatedId = useId();
  const ids = { title: titleId ?? `${generatedId}-title`, body: `${generatedId}-body` };

  return (
    <div
      ref={ref}
      style={style}
      className={cn("flex flex-col gap-4 rounded-xl border border-border bg-background px-4 py-3", className)}
    >
      <div className="flex items-center gap-2">
        {leading}
        <CollapsibleItemToggle
          openKey={openKey}
          isOpen={isOpen}
          onToggle={() => uiState.toggle(openKey)}
          titleId={ids.title}
          bodyId={ids.body}
          title={title}
          placeholderTitle={placeholderTitle}
          srTitlePrefix={srTitlePrefix}
          summary={summary}
          hasError={hasError}
        />
        {trailing}
      </div>
      {/* 머리 줄 위 여백(py-3)보다 펼친 본문 아래 여백을 4px 더 줘 좌우(px-4)와 맞춘다. */}
      <div id={ids.body} role="group" aria-labelledby={ids.title} hidden={!isOpen} className="flex flex-col gap-4 pb-1">
        {children}
      </div>
    </div>
  );
}
