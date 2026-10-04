import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_STEP_ROUTES } from "../config/guideRoutes";
import { GUIDE_CLICK_CARD_CLASS } from "../config/guideStyles";
import type { GuideStep } from "../model/toGuidePages";

const HEADING_ID = "steps-title";

type GuideStepListProps = {
  topicId: CreationGuideTopicId;
  steps: readonly GuideStep[];
};

/**
 * 개요의 단계 목록 — 빌더 탭 순서 그대로의 단계 페이지 링크. 번호는 장식이 아니라 실제 순서다. 둘째 줄은 단계마다 따로
 * 쓴 짧은 요약이라 좁은 두 열 카드에서도 한 줄에 든다(말줄임은 글자 수 검사가 놓친 경우의 안전망).
 */
export function GuideStepList({ topicId, steps }: GuideStepListProps) {
  return (
    <section aria-labelledby={HEADING_ID} className="flex flex-col gap-4">
      <h2 id={HEADING_ID} className="text-xl font-semibold tracking-tight text-balance text-foreground">
        빌더 {steps.length}단계
      </h2>
      <ol className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2">
        {steps.map((step) => (
          <li key={step.id} className="min-w-0">
            <Link
              to={GUIDE_STEP_ROUTES[topicId]}
              params={{ step: step.id }}
              className={cn(GUIDE_CLICK_CARD_CLASS, "flex items-center gap-3 px-4 py-3")}
            >
              <span className="w-5 shrink-0 text-sm font-semibold text-muted-foreground tabular-nums">{step.index + 1}</span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-sm font-semibold text-foreground">{step.label}</span>
                <span className="truncate text-xs text-muted-foreground">{step.summary}</span>
              </span>
              <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
