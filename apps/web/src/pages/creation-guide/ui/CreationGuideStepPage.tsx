import { Link, Navigate } from "@tanstack/react-router";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { GUIDE_OVERVIEW_ROUTES, GUIDE_STEP_ROUTES } from "../config/guideRoutes";
import { useGuidePages } from "../model/useGuidePages";
import { GuideContent } from "./GuideContent";
import { GuideMarkdown } from "./GuideMarkdown";

type CreationGuideStepPageProps = {
  topicId: CreationGuideTopicId;
  stepId: string;
};

/**
 * `/guide/<토픽>/<탭 id>` 단계 페이지. 빌더 탭 하나와 1:1 이다. 모르는 단계 id 면 개요로 바꿔 보낸다 — 서버(Worker)는
 * 단계 id 를 모른 채 어떤 값에도 페이지를 내주므로 화면에서 고른다. 라우트의 진입 훅이 아니라 여기서 하는 이유: 가이드
 * 라우트에 진입 훅이 없다는 검사가 로그인 가드가 끼어드는 것을 막는 장치라, 훅을 두면 그 검사가 뜻을 잃는다.
 *
 * 임시 마크업이다 — 라우트·원고 모델이 맞물리는지만 보인다. 단계 칩·목업·이전/다음 모양은 디자인 작업에서 갈아 끼운다.
 */
export function CreationGuideStepPage({ topicId, stepId }: CreationGuideStepPageProps) {
  const { topic, pages } = useGuidePages(topicId);
  const step = pages.steps.find((candidate) => candidate.id === stepId);
  if (!step) return <Navigate to={GUIDE_OVERVIEW_ROUTES[topicId]} replace />;

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-8 px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-4">
        <Link to={GUIDE_OVERVIEW_ROUTES[topicId]} className="text-sm text-muted-foreground">
          ‹ {topic.title}
        </Link>
        <nav aria-label="작성 단계">
          <ol className="flex flex-wrap gap-3 text-sm">
            {pages.steps.map((candidate) => (
              <li key={candidate.id}>
                <Link
                  to={GUIDE_STEP_ROUTES[topicId]}
                  params={{ step: candidate.id }}
                  aria-current={candidate.id === step.id ? "page" : undefined}
                >
                  {candidate.label}
                </Link>
              </li>
            ))}
          </ol>
        </nav>
        <h1 className="text-2xl font-bold tracking-tight text-balance text-foreground">{step.title}</h1>
        {step.lead && <GuideMarkdown source={step.lead} />}
      </div>
      <GuideContent content={step.content} />
      <nav aria-label="단계 이동" className="grid grid-cols-2 gap-3 text-sm">
        {step.prevId ? (
          <Link to={GUIDE_STEP_ROUTES[topicId]} params={{ step: step.prevId }}>
            ‹ 이전 단계
          </Link>
        ) : (
          <Link to={GUIDE_OVERVIEW_ROUTES[topicId]}>‹ 개요</Link>
        )}
        {step.nextId ? (
          <Link to={GUIDE_STEP_ROUTES[topicId]} params={{ step: step.nextId }} className="text-right">
            다음 단계 ›
          </Link>
        ) : (
          <Link to={GUIDE_OVERVIEW_ROUTES[topicId]} className="text-right">
            개요 ›
          </Link>
        )}
      </nav>
    </main>
  );
}
