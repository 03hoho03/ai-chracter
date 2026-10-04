import { CHARACTER_TABS } from "@/features/build-character";
import { STORY_TABS } from "@/features/build-story";
import { CREATION_GUIDE_TOPIC_IDS, type CreationGuideTopicId } from "@/shared/config/creationGuide";

import characterManuscript from "../manuscripts/character.md?raw";
import storyManuscript from "../manuscripts/story.md?raw";
import { STORY_FIELD_MOCKUPS, type StoryFieldMockups } from "./storyFieldMockups";

export type GuideTopic = {
  id: CreationGuideTopicId;
  title: string;
  manuscript: string;
  steps: readonly { id: string; label: string }[];
  /** 칸 블록(빌더 칸 모양 목업)을 쓰는 토픽만 둔다. 없으면 원고에 칸 블록을 쓸 수 없다. */
  fieldMockups?: StoryFieldMockups;
};

/**
 * 토픽 id 마다 원고와 제목. 키가 토픽 id 목록 전체라, 토픽을 더하면 여기 항목이 없다는 타입 에러가 난다.
 *
 * `steps` 는 그 빌더의 탭 목록이다. 탭 하나가 단계 페이지 하나(`/guide/<토픽>/<탭 id>`)이고, 원고의 단계 절은 탭 id 를
 * 절 id 로 탭 순서대로 한 번씩 써야 한다 — 빌더에 탭이 생기면 원고에 절이 빠진 것이 원고 검사에서 드러난다.
 */
const TOPIC_CONTENT: Record<CreationGuideTopicId, Omit<GuideTopic, "id">> = {
  story: {
    title: "스토리 작성 가이드",
    manuscript: storyManuscript,
    steps: STORY_TABS,
    fieldMockups: STORY_FIELD_MOCKUPS,
  },
  character: { title: "캐릭터 작성 가이드", manuscript: characterManuscript, steps: CHARACTER_TABS },
};

/**
 * 작성 가이드 토픽 목록. 토픽 하나 = 토픽 id 한 줄(`shared/config/creationGuide.ts`) + 원고 파일 하나 + 위 항목 하나 +
 * 라우트 파일 둘(`routes/guide.<id>.index.tsx` 개요, `routes/guide.<id>.$step.tsx` 단계) + Worker 의 알려진 경로 목록 두 줄.
 */
export const GUIDE_TOPICS: readonly GuideTopic[] = CREATION_GUIDE_TOPIC_IDS.map((id) => ({
  id,
  ...TOPIC_CONTENT[id],
}));

export function findGuideTopic(topicId: CreationGuideTopicId): GuideTopic {
  const topic = GUIDE_TOPICS.find((candidate) => candidate.id === topicId);
  if (!topic) throw new Error(`작성 가이드 토픽이 없다: ${topicId}`);
  return topic;
}
