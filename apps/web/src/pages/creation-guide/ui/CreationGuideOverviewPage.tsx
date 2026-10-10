import { Navigate, useLocation } from "@tanstack/react-router";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_STEP_ROUTES } from "../config/guideRoutes";
import type { ManuscriptSection } from "../model/parseManuscript";
import { legacyStepFromHash } from "../model/toGuidePages";
import { useGuidePages } from "../model/useGuidePages";
import { GuideContent } from "./GuideContent";
import { GuideExampleWork } from "./GuideExampleWork";
import { GuideReadTimingList } from "./GuideReadTimingList";
import { GuideStepList } from "./GuideStepList";

/** 원고 첫 절(들어가며). 제목 없이 페이지 제목 아래 리드로 그린다. */
const INTRO_SECTION_ID = "overview";
/** "AI가 칸을 읽는 때" 절. 원고에는 리드 문장만 있고 그룹 목록은 목업 표에서 그린다. */
const READ_TIMING_SECTION_ID = "reading";

type CreationGuideOverviewPageProps = {
  topicId: CreationGuideTopicId;
};

/**
 * `/guide/<토픽>` 개요 — 들어가는 글과 (스토리) 예시 작품, 단계 목록, AI가 칸을 읽는 때, 미리보기·실수 같은 단계 밖 절.
 * 단계 목록을 읽는 때 표보다 앞에 두는 이유: 개요에 온 사람이 먼저 찾는 것은 어느 단계로 갈지다.
 * 로그인 없이 열린다(빌더에서 새 탭으로 연다). 산문이 주인이라 넓은 화면에서도 읽기 폭 한 열이다.
 */
export function CreationGuideOverviewPage({ topicId }: CreationGuideOverviewPageProps) {
  const { topic, pages, mockupContext } = useGuidePages(topicId);
  const hash = useLocation({ select: (location) => location.hash });

  // 옛 한 페이지 가이드의 단계 앵커로 들어온 링크(`#setting`)는 그 단계 페이지로 바꾼다. 개요 안 앵커는 그대로 둔다.
  const legacyStepId = legacyStepFromHash(hash, topic.steps.map((step) => step.id));
  if (legacyStepId) return <Navigate to={GUIDE_STEP_ROUTES[topicId]} params={{ step: legacyStepId }} replace />;

  const intro = pages.overview.before.find((section) => section.id === INTRO_SECTION_ID);
  const beforeSections = pages.overview.before.filter((section) => section !== intro);

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-10 px-4 py-10 sm:px-6">
      <div id={intro?.id} className="flex scroll-mt-20 flex-col gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-balance text-foreground">{topic.title}</h1>
        {intro && <GuideContent content={intro.content} headingLevel={2} />}
        {mockupContext && <GuideExampleWork context={mockupContext} />}
      </div>
      <GuideStepList topicId={topicId} steps={pages.steps} />
      {beforeSections.map((section) => (
        <OverviewSection key={section.id} section={section}>
          {section.id === READ_TIMING_SECTION_ID && mockupContext && (
            <GuideReadTimingList
              topicId={topicId}
              mockups={mockupContext.mockups}
              anchorOfKey={pages.anchorOfKey}
              steps={pages.steps}
              labelledBy={headingIdOf(section)}
            />
          )}
        </OverviewSection>
      ))}
      {pages.overview.after.map((section) => (
        <OverviewSection key={section.id} section={section} />
      ))}
    </main>
  );
}

type OverviewSectionProps = {
  section: ManuscriptSection;
  children?: React.ReactNode;
};

/** 절 제목은 앵커로 이동했을 때 전역 헤더(sticky, 경계선 포함 57px) 아래로 숨지 않도록 위 여백을 남긴다. */
function OverviewSection({ section, children }: OverviewSectionProps) {
  return (
    <section id={section.id} aria-labelledby={headingIdOf(section)} className="flex scroll-mt-20 flex-col gap-4">
      <h2 id={headingIdOf(section)} className="text-xl font-semibold tracking-tight text-balance text-foreground">
        {section.title}
      </h2>
      {/* 실수 목록처럼 칸 링크가 여럿 몰리는 절이라 강조색 대신 흐린 밑줄 링크로 그린다. */}
      <GuideContent content={section.content} linkTone="quiet" />
      {children}
    </section>
  );
}

function headingIdOf(section: ManuscriptSection): string {
  return `${section.id}-title`;
}
