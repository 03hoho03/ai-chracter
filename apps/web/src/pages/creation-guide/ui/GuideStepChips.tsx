import { toggleVariants } from "@ai-character-chat/ui/components/toggle";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { useLayoutEffect, useRef } from "react";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";
import { useHorizontalScrollClip } from "@/shared/lib/scroll/useHorizontalScrollClip";

import { GUIDE_STEP_ROUTES } from "../config/guideRoutes";
import type { GuideStep } from "../model/toGuidePages";

/** 오른쪽 페이드 폭(`w-8`). 현재 칩을 끌어올 때 이만큼 더 당겨 페이드에 덮이지 않게 한다. */
const FADE_WIDTH = 32;

type GuideStepChipsProps = {
  topicId: CreationGuideTopicId;
  topicTitle: string;
  steps: readonly GuideStep[];
  currentStepId: string;
};

/**
 * 단계 칩 — 빌더 탭 바와 같은 이름·순서라 "지금 빌더의 이 탭"으로 읽힌다. 탭이 아니라 다른 주소로 가는 링크라 Radix 탭을
 * 쓰지 않고 링크에 탭 모양(`toggleVariants` 의 tab)만 빌린다. 현재 단계는 밑줄과 `aria-current="page"` 로 알린다.
 *
 * 화면 위에 붙여 두지 않는다(sticky 아님) — 이 시스템의 붙박이 줄은 전역 헤더 하나뿐이다.
 *
 * 좁은 화면에서 뒤쪽 단계의 칩은 가로로 밖에 있어, 단계가 바뀔 때마다 칩 줄의 가로 위치만 현재 칩이 보이게 맞춘다.
 * `scrollIntoView` 를 쓰지 않는 이유: 칩이 세로로 화면 밖이면(칸 앵커로 아래에서 들어온 경우) 창까지 위로 끌어올려 앵커
 * 이동을 무른다. 부드러운 스크롤 없이 즉시 옮긴다.
 */
export function GuideStepChips({ topicId, topicTitle, steps, currentStepId }: GuideStepChipsProps) {
  const clip = useHorizontalScrollClip();
  const listRef = useRef<HTMLOListElement>(null);

  // `$step` 파라미터 라우트라 단계 사이를 오가도 이 컴포넌트가 다시 마운트되지 않을 수 있어 단계 id 를 의존값으로 둔다.
  useLayoutEffect(() => {
    const list = listRef.current;
    const scroller = list?.parentElement;
    const chip = list?.querySelector('[aria-current="page"]');
    if (!scroller || !chip) return;
    const scrollerRect = scroller.getBoundingClientRect();
    const chipRect = chip.getBoundingClientRect();
    const paddingLeft = parseFloat(getComputedStyle(scroller).paddingLeft);
    if (chipRect.right > scrollerRect.right) scroller.scrollLeft += chipRect.right - scrollerRect.right + FADE_WIDTH;
    else if (chipRect.left < scrollerRect.left + paddingLeft) {
      // 비교 기준은 테두리 상자라 패딩(포커스 링 여유)만큼 더 돌려야 첫 칩이 스크롤러 왼쪽 끝에 붙지 않는다.
      scroller.scrollLeft -= scrollerRect.left + paddingLeft - chipRect.left;
    }
  }, [currentStepId]);

  return (
    <nav aria-label={`${topicTitle} 단계`} className="relative">
      {/* 가로 스크롤 상자는 포커스 링을 네 방향 모두 자른다 — 안팎으로 링 두께만큼 상쇄한다. */}
      <div ref={clip.ref} className="-m-1 overflow-x-auto overflow-y-hidden p-1">
        <ol ref={listRef} className="flex w-max">
          {steps.map((step) => {
            const isCurrent = step.id === currentStepId;
            return (
              <li key={step.id}>
                <Link
                  to={GUIDE_STEP_ROUTES[topicId]}
                  params={{ step: step.id }}
                  aria-current={isCurrent ? "page" : undefined}
                  data-state={isCurrent ? "on" : "off"}
                  className={cn(toggleVariants({ variant: "tab" }), "shrink-0")}
                >
                  {step.label}
                </Link>
              </li>
            );
          })}
        </ol>
      </div>
      {clip.isClippedRight && (
        <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-linear-to-l from-background" />
      )}
    </nav>
  );
}
