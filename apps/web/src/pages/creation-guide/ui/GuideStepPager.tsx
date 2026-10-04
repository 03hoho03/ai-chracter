import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_OVERVIEW_ROUTES, GUIDE_STEP_ROUTES } from "../config/guideRoutes";
import { GUIDE_CLICK_CARD_CLASS } from "../config/guideStyles";
import type { GuideStep } from "../model/toGuidePages";

const CARD_LAYOUT = "flex min-w-0 flex-col gap-0.5 px-4 py-3";

type GuideStepPagerProps = {
  topicId: CreationGuideTopicId;
  steps: readonly GuideStep[];
  step: GuideStep;
  /** 마지막 단계 다음에 가는 개요 절(미리보기로 시험하기). 그런 절이 없는 토픽은 null 이고 개요 첫머리로 간다. */
  finish: { anchorId: string; title: string } | null;
};

/**
 * 이전/다음 단계. 두 칸 모두 무채 클릭 카드다 — 이 페이지에는 "지금 눌러야 할 단 하나"가 없어 강조 채움을 쓰지 않는다.
 * 첫 단계의 이전은 개요, 마지막 단계의 다음은 개요의 미리보기 절이다 — 단계를 다 본 사람이 할 일이 시험해 보는 것이라서다.
 */
export function GuideStepPager({ topicId, steps, step, finish }: GuideStepPagerProps) {
  const prev = steps.find((candidate) => candidate.id === step.prevId);
  const next = steps.find((candidate) => candidate.id === step.nextId);

  return (
    <nav aria-label="단계 이동" className="grid grid-cols-2 gap-3">
      {prev ? (
        <Link to={GUIDE_STEP_ROUTES[topicId]} params={{ step: prev.id }} className={cn(GUIDE_CLICK_CARD_CLASS, CARD_LAYOUT)}>
          <PagerText direction="prev" kicker="이전 단계" title={`${prev.index + 1} ${prev.label}`} />
        </Link>
      ) : (
        <Link
          to={GUIDE_OVERVIEW_ROUTES[topicId]}
          activeOptions={{ exact: true }}
          className={cn(GUIDE_CLICK_CARD_CLASS, CARD_LAYOUT)}
        >
          <PagerText direction="prev" kicker="처음으로" title="개요" />
        </Link>
      )}
      {next ? (
        <Link
          to={GUIDE_STEP_ROUTES[topicId]}
          params={{ step: next.id }}
          className={cn(GUIDE_CLICK_CARD_CLASS, CARD_LAYOUT, "col-start-2 items-end text-right")}
        >
          <PagerText direction="next" kicker="다음 단계" title={`${next.index + 1} ${next.label}`} />
        </Link>
      ) : (
        <Link
          to={GUIDE_OVERVIEW_ROUTES[topicId]}
          hash={finish?.anchorId}
          activeOptions={{ exact: true }}
          className={cn(GUIDE_CLICK_CARD_CLASS, CARD_LAYOUT, "col-start-2 items-end text-right")}
        >
          <PagerText direction="next" kicker="다 채웠다면" title={finish?.title ?? "개요"} />
        </Link>
      )}
    </nav>
  );
}
type PagerTextProps = {
  direction: "prev" | "next";
  kicker: string;
  title: string;
};

function PagerText({ direction, kicker, title }: PagerTextProps) {
  const Icon = direction === "prev" ? ChevronLeft : ChevronRight;
  return (
    <>
      <span
        className={cn(
          "flex items-center gap-0.5 text-xs text-muted-foreground",
          direction === "next" && "flex-row-reverse",
        )}
      >
        <Icon aria-hidden className="size-3.5 shrink-0" />
        {kicker}
      </span>
      <span className="truncate text-sm font-semibold text-foreground">{title}</span>
    </>
  );
}
