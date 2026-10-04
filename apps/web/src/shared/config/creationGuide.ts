/**
 * 작성 가이드 토픽 id 의 단일 소스. 가이드 페이지(토픽 등록)와 빌더 상단바(가이드 링크 경로)가 둘 다 이
 * 목록에서 도출한다 — 두 레이어가 각자 목록을 적으면 한쪽에만 토픽이 추가된다.
 *
 * 토픽을 더하면 `pages/creation-guide/config/topics.ts` 가 그 원고를 요구하고(타입 에러), 라우트 파일
 * `routes/guide.<id>.index.tsx`·`routes/guide.<id>.$step.tsx` 와 Worker 의 알려진 경로 목록은 각자의 대조 테스트가 요구한다.
 */
export const CREATION_GUIDE_TOPIC_IDS = ["story", "character"] as const;

export type CreationGuideTopicId = (typeof CREATION_GUIDE_TOPIC_IDS)[number];

export type CreationGuidePath = `/guide/${CreationGuideTopicId}` | `/guide/${CreationGuideTopicId}/${string}`;

/**
 * 가이드 경로. 단계 id(빌더 탭 id)를 주면 그 단계 페이지다. 이 레이어는 빌더 탭 목록을 모르므로 단계 id 는 문자열로
 * 받는다 — 모르는 id 는 가이드 페이지가 개요로 돌려보낸다.
 */
export function creationGuidePath(topicId: CreationGuideTopicId, stepId?: string): CreationGuidePath {
  return stepId === undefined ? `/guide/${topicId}` : `/guide/${topicId}/${stepId}`;
}
