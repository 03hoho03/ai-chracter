import { useMemo } from "react";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";
import { assertNever } from "@/shared/lib/assertNever";

import { GUIDE_TOPICS } from "../config/topics";
import { parseManuscript } from "../model/parseManuscript";
import { type GuideBlock, type GuideSection, toGuideLayout } from "../model/toGuideLayout";
import { GuideConversation } from "./GuideConversation";
import { GuideFieldExample } from "./GuideFieldExample";
import { GuideMarkdown } from "./GuideMarkdown";
import { GuideToc } from "./GuideToc";

type CreationGuidePageProps = {
  topicId: CreationGuideTopicId;
};

/**
 * `/guide/<토픽>` 공용 페이지 — 토픽마다 원고만 다르고 그리는 방식은 같아, 라우트 파일이 토픽 id 만 넘긴다.
 * 로그인 없이 열린다(빌더에서 새 탭으로 연다). 원고는 번들에 실린 정적 글이라 조회·로딩 상태가 없다.
 *
 * 폭은 약관 문서와 같은 `max-w-2xl` 한 컬럼이다. 목차는 제목 아래 본문 흐름 안에 두고, 첫 절 제목 앞의
 * 들어가는 글이 있으면 목차보다 먼저 보인다.
 */
export function CreationGuidePage({ topicId }: CreationGuidePageProps) {
  const topic = findGuideTopic(topicId);
  const { toc, layout } = useMemo(() => {
    const manuscript = parseManuscript(topic.manuscript);
    return { toc: manuscript.toc, layout: toGuideLayout(manuscript.segments) };
  }, [topic]);

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-10 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-balance text-foreground">{topic.title}</h1>
        <GuideBlocks blocks={layout.lead} />
      </div>
      {toc.length > 0 && <GuideToc entries={toc} />}
      {layout.sections.map((section) => (
        <GuideSectionView key={section.id} section={section} />
      ))}
    </main>
  );
}

function findGuideTopic(topicId: CreationGuideTopicId) {
  const topic = GUIDE_TOPICS.find((candidate) => candidate.id === topicId);
  if (!topic) throw new Error(`작성 가이드 토픽이 없다: ${topicId}`);
  return topic;
}

type GuideSectionViewProps = {
  section: GuideSection;
};

/** 절 제목은 앵커로 이동했을 때 전역 헤더(sticky 56px) 아래로 숨지 않도록 위 여백을 남긴다. */
function GuideSectionView({ section }: GuideSectionViewProps) {
  return (
    <section aria-labelledby={section.id} className="flex flex-col gap-4">
      <h2 id={section.id} className="scroll-mt-20 text-xl font-semibold tracking-tight text-balance text-foreground">
        {section.title}
      </h2>
      <GuideBlocks blocks={section.blocks} />
    </section>
  );
}

type GuideBlocksProps = {
  blocks: GuideBlock[];
};

// 블록은 원고에서 온 고정 목록이라 순서가 바뀌지 않아 위치를 key 로 쓴다.
function GuideBlocks({ blocks }: GuideBlocksProps) {
  return blocks.map((block, index) => {
    switch (block.kind) {
      case "markdown":
        return <GuideMarkdown key={index} source={block.source} />;
      case "conversation":
        return <GuideConversation key={index} messages={block.messages} />;
      case "field":
        return <GuideFieldExample key={index} body={block.body} />;
      default:
        return assertNever(block);
    }
  });
}
