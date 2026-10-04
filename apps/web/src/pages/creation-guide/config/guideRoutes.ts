import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

/**
 * 토픽마다 개요·단계 라우트 경로. 화면 안 링크와 되돌려 보내기가 라우터의 타입 검사를 받도록 등록된 경로 글자를 그대로
 * 쓴다(토픽 id 를 끼워 만든 문자열은 라우터가 어느 라우트인지 확인하지 못한다).
 */
export const GUIDE_OVERVIEW_ROUTES = {
  story: "/guide/story",
  character: "/guide/character",
} as const satisfies Record<CreationGuideTopicId, string>;

export const GUIDE_STEP_ROUTES = {
  story: "/guide/story/$step",
  character: "/guide/character/$step",
} as const satisfies Record<CreationGuideTopicId, string>;
