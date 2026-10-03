import { Link, Navigate, useLocation } from "@tanstack/react-router";

import { STORY_FIELD_LABELS } from "@/features/build-story";
import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_STEP_ROUTES } from "../config/guideRoutes";
import { READ_TIMING_GROUPS, type StoryFieldMockups } from "../config/storyFieldMockups";
import { isStoryFieldKey } from "../model/mockupCaption";
import type { ManuscriptSection } from "../model/parseManuscript";
import type { GuideAnchor } from "../model/toGuidePages";
import { legacyStepFromHash } from "../model/toGuidePages";
import { useGuidePages } from "../model/useGuidePages";
import { GuideContent } from "./GuideContent";

type CreationGuideOverviewPageProps = {
  topicId: CreationGuideTopicId;
};

/** "칸을 AI가 읽는 때" 그룹 목록을 붙이는 개요 절. 목록은 원고가 아니라 목업 표에서 그린다. */
const READ_TIMING_SECTION_ID = "reading";

/**
 * `/guide/<토픽>` 개요 — 들어가는 글, (스토리) AI가 읽는 때 목록, 단계 목록, 미리보기·실수 같은 단계 밖 절.
 * 로그인 없이 열린다(빌더에서 새 탭으로 연다).
 *
 * 임시 마크업이다 — 라우트·옛 해시 호환·원고 모델이 맞물리는지만 보인다. 모양은 디자인 작업에서 갈아 끼운다.
 */
export function CreationGuideOverviewPage({ topicId }: CreationGuideOverviewPageProps) {
  const { topic, pages } = useGuidePages(topicId);
  const hash = useLocation({ select: (location) => location.hash });

  // 옛 한 페이지 가이드의 단계 앵커로 들어온 링크(`#setting`)는 그 단계 페이지로 바꾼다. 개요 안 앵커는 그대로 둔다.
  const legacyStepId = legacyStepFromHash(hash, topic.steps.map((step) => step.id));
  if (legacyStepId) return <Navigate to={GUIDE_STEP_ROUTES[topicId]} params={{ step: legacyStepId }} replace />;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-10 px-4 py-10 sm:px-6">
      <h1 className="text-2xl font-bold tracking-tight text-balance text-foreground">{topic.title}</h1>
      {pages.overview.before.map((section) => (
        <OverviewSection key={section.id} section={section}>
          {section.id === READ_TIMING_SECTION_ID && topic.fieldMockups && (
            <ReadTimingList topicId={topicId} mockups={topic.fieldMockups} anchorOfKey={pages.anchorOfKey} />
          )}
        </OverviewSection>
      ))}
      <ol className="flex flex-col gap-2">
        {pages.steps.map((step) => (
          <li key={step.id}>
            <Link to={GUIDE_STEP_ROUTES[topicId]} params={{ step: step.id }} className="flex flex-col text-sm">
              <span className="font-semibold text-foreground">
                {step.index + 1} {step.label}
              </span>
              <span className="truncate text-xs text-muted-foreground">{step.summary}</span>
            </Link>
          </li>
        ))}
      </ol>
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

/** 절 제목은 앵커로 이동했을 때 전역 헤더(sticky 56px) 아래로 숨지 않도록 위 여백을 남긴다. */
function OverviewSection({ section, children }: OverviewSectionProps) {
  return (
    <section aria-labelledby={section.id} className="flex flex-col gap-4">
      <h2 id={section.id} className="scroll-mt-20 text-xl font-semibold tracking-tight text-balance text-foreground">
        {section.title}
      </h2>
      <GuideContent content={section.content} />
      {children}
    </section>
  );
}

type ReadTimingListProps = {
  topicId: CreationGuideTopicId;
  mockups: StoryFieldMockups;
  anchorOfKey: ReadonlyMap<string, GuideAnchor>;
};

function ReadTimingList({ topicId, mockups, anchorOfKey }: ReadTimingListProps) {
  return (
    <ul className="flex flex-col gap-5">
      {READ_TIMING_GROUPS.map((group) => {
        const keys = Object.keys(mockups).filter(
          (key) => isStoryFieldKey(key) && mockups[key].readTiming === group.id,
        );
        return (
          <li key={group.id} className="flex flex-col gap-1.5 text-sm">
            <span className="font-semibold text-foreground">{group.title}</span>
            <span className="text-muted-foreground">
              {keys.map((key) => {
                const anchor = anchorOfKey.get(key);
                const label = isStoryFieldKey(key) ? STORY_FIELD_LABELS[key].label : key;
                if (!anchor) return null;
                return (
                  <Link
                    key={key}
                    to={GUIDE_STEP_ROUTES[topicId]}
                    params={{ step: anchor.stepId }}
                    hash={anchor.anchorId}
                    className="mr-2 underline underline-offset-4"
                  >
                    {label}
                  </Link>
                );
              })}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
