import { CHARACTER_TABS } from "@/features/build-character";
import { STORY_TABS } from "@/features/build-story";
import { CREATION_GUIDE_TOPIC_IDS, type CreationGuideTopicId } from "@/shared/config/creationGuide";

import characterManuscript from "../manuscripts/character.md?raw";
import storyManuscript from "../manuscripts/story.md?raw";

export type GuideTopic = {
  id: CreationGuideTopicId;
  title: string;
  manuscript: string;
  steps?: readonly { id: string }[];
};

/**
 * 토픽 id 마다 원고와 제목. 키가 토픽 id 목록 전체라, 토픽을 더하면 여기 항목이 없다는 타입 에러가 난다.
 *
 * `steps` 는 그 빌더의 탭 목록이다. 원고 검사 테스트가 탭 id 가 원고 절 id 로 탭 순서대로 한 번씩 나오는지
 * 보는 데 쓴다 — 빌더에 탭이 생기면 원고에 절이 빠진 것이 테스트에서 드러난다. 빌더 탭과 짝이 없는
 * 토픽(예: 이미지 생성)은 `steps` 를 빼면 그 검사를 건너뛴다.
 */
const TOPIC_CONTENT: Record<CreationGuideTopicId, Omit<GuideTopic, "id">> = {
  story: { title: "스토리 작성 가이드", manuscript: storyManuscript, steps: STORY_TABS },
  character: { title: "캐릭터 작성 가이드", manuscript: characterManuscript, steps: CHARACTER_TABS },
};

/**
 * 작성 가이드 토픽 목록. 토픽 하나 = 토픽 id 한 줄(`shared/config/creationGuide.ts`) + 원고 파일 하나 +
 * 위 항목 하나 + 라우트 파일 `routes/guide.<id>.tsx` 하나(+ Worker 의 알려진 경로 목록 한 줄).
 */
export const GUIDE_TOPICS: readonly GuideTopic[] = CREATION_GUIDE_TOPIC_IDS.map((id) => ({
  id,
  ...TOPIC_CONTENT[id],
}));
