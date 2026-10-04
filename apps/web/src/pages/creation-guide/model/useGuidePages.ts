import { useMemo } from "react";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { findGuideTopic } from "../config/topics";
import { toGuideMockupContext } from "./guideMockupContext";
import { parseManuscript } from "./parseManuscript";
import { toGuidePages } from "./toGuidePages";

/**
 * 토픽 원고를 개요·단계 페이지로 나눈 결과. 원고는 번들에 실린 정적 글이라 조회·로딩 상태가 없다. 칸 목업이 있는 토픽만
 * `mockupContext` 가 있다.
 */
export function useGuidePages(topicId: CreationGuideTopicId) {
  return useMemo(() => {
    const topic = findGuideTopic(topicId);
    const pages = toGuidePages(parseManuscript(topic.manuscript), topic);
    const mockupContext = topic.fieldMockups ? toGuideMockupContext(pages.steps, topic.fieldMockups) : undefined;
    return { topic, pages, mockupContext };
  }, [topicId]);
}
