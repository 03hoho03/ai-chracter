import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, Navigate } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_OVERVIEW_ROUTES } from "../config/guideRoutes";
import { useGuidePages } from "../model/useGuidePages";
import { GuideContent } from "./GuideContent";
import { GuideMarkdown } from "./GuideMarkdown";
import { GuideStepChips } from "./GuideStepChips";
import { GuideStepPager } from "./GuideStepPager";

/** 개요의 "미리보기로 시험하기" 절 id. 마지막 단계의 다음 칸이 그리로 간다. */
const PREVIEW_SECTION_ID = "preview";

type CreationGuideStepPageProps = {
  topicId: CreationGuideTopicId;
  stepId: string;
};

/**
 * `/guide/<토픽>/<탭 id>` 단계 페이지. 빌더 탭 하나와 1:1 이다. 모르는 단계 id 면 개요로 바꿔 보낸다 — 서버(Worker)는
 * 단계 id 를 모른 채 어떤 값에도 페이지를 내주므로 화면에서 고른다. 라우트의 진입 훅이 아니라 여기서 하는 이유: 가이드
 * 라우트에 진입 훅이 없다는 검사가 로그인 가드가 끼어드는 것을 막는 장치라, 훅을 두면 그 검사가 뜻을 잃는다.
 *
 * 칸 블록이 있는 토픽(스토리)은 넓은 화면에서 설명 ↔ 칸 그림 두 열이라 본문 폭을 넓히고, 산문뿐인 토픽(캐릭터)은 읽기
 * 폭 한 열 그대로다. 단계를 옮기면 라우터가 창을 맨 위로, `#칸 키` 로 들어오면 그 칸 블록으로 스크롤한다.
 */
export function CreationGuideStepPage({ topicId, stepId }: CreationGuideStepPageProps) {
  const { topic, pages, mockupContext } = useGuidePages(topicId);
  const step = pages.steps.find((candidate) => candidate.id === stepId);
  if (!step) return <Navigate to={GUIDE_OVERVIEW_ROUTES[topicId]} replace />;

  const previewSection = pages.overview.after.find((section) => section.id === PREVIEW_SECTION_ID);

  return (
    <main
      className={cn(
        "mx-auto flex w-full max-w-2xl flex-col gap-8 px-4 py-10 sm:px-6",
        mockupContext && "lg:max-w-5xl lg:gap-10",
      )}
    >
      <div className="flex flex-col gap-4">
        {/* 라우터 링크는 기본으로 하위 경로에서도 "현재 페이지"로 표시돼, 정확히 개요일 때만 그렇게 읽히게 한다. */}
        <Link
          to={GUIDE_OVERVIEW_ROUTES[topicId]}
          activeOptions={{ exact: true }}
          className="-mx-2 inline-flex h-9 w-fit items-center gap-1 rounded-lg border border-transparent px-2 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <ChevronLeft aria-hidden className="size-4 shrink-0" />
          {topic.title}
        </Link>
        <GuideStepChips topicId={topicId} topicTitle={topic.title} steps={pages.steps} currentStepId={step.id} />
        <h1 className="text-2xl font-bold tracking-tight text-balance text-foreground">{step.title}</h1>
        {step.lead && <GuideMarkdown source={step.lead} className="max-w-2xl text-muted-foreground" />}
      </div>
      {mockupContext ? (
        <GuideContent content={step.content} mockupContext={mockupContext} />
      ) : (
        <div className="flex flex-col gap-4">
          <GuideContent content={step.content} headingLevel={2} />
        </div>
      )}
      <GuideStepPager
        topicId={topicId}
        steps={pages.steps}
        step={step}
        finish={previewSection ? { anchorId: previewSection.id, title: previewSection.title } : null}
      />
    </main>
  );
}
