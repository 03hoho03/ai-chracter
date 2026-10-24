import { cn } from "@ai-character-chat/ui/lib/utils";
import type { RefObject } from "react";

import type { NovelDetailResponse } from "@/entities/novel";
import { NovelSourceSelectionStep } from "@/features/select-novel-source";

type NovelPlanDocumentProps = {
  novel: NovelDetailResponse;
  /** 문서 제목. 구성 모드로 옮기면 호출부가 여기로 포커스를 보낸다. */
  headingRef: RefObject<HTMLHeadingElement | null>;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/** 구성 단계. 차례가 곧 정보라(앞 단계를 승인해야 다음 단계가 이어진다) 번호를 단다. */
const STEPS = ["담을 대화", "전체 구성안", "화별 장면·원고"] as const;

/**
 * 편집 보드의 구성 모드(`?select=plan`) — 대화를 골라 화 구성을 세우는 한 열 문서. 넓은 화면에서도 캔버스·옆 패널 대신 이
 * 문서 하나가 보이고(폭은 호출부가 정한다), 상단바·작업 줄·떠날 때의 버림 확인은 보드 것을 그대로 쓴다.
 *
 * 지금은 첫 단계(담을 대화)만 있다. 단계 줄은 앞으로 이어질 차례를 보인다.
 */
export function NovelPlanDocument({ novel, headingRef, onDraftDirtyChange }: NovelPlanDocumentProps) {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        {/* 조작 대상이 아니라 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
        <h2 ref={headingRef} tabIndex={-1} className="text-xl font-semibold tracking-tight text-foreground outline-none">
          구성
        </h2>
        <p className="text-sm break-keep text-muted-foreground">
          소설에 담을 대화를 고르고 승인하면, 그 대화로 화 구성을 세워 화마다 원고를 써요.
        </p>
        <ol aria-label="구성 단계" className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {STEPS.map((step, index) => (
            <li
              key={step}
              aria-current={index === 0 ? "step" : undefined}
              className={cn("flex items-center gap-1.5", index === 0 ? "font-medium text-foreground" : "text-muted-foreground")}
            >
              <span
                aria-hidden
                className={cn(
                  "flex size-5 items-center justify-center rounded-full border text-xs tabular-nums",
                  index === 0 ? "border-foreground" : "border-border",
                )}
              >
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>
      <NovelSourceSelectionStep novel={novel} onDraftDirtyChange={onDraftDirtyChange} />
    </div>
  );
}
