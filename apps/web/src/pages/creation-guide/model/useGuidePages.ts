import { useMemo } from "react";

import type { CreationGuideTopicId } from "@/shared/config/creationGuide";

import { findGuideTopic } from "../config/topics";
import { parseManuscript } from "./parseManuscript";
import { toGuidePages } from "./toGuidePages";

/** 토픽 원고를 개요·단계 페이지로 나눈 결과. 원고는 번들에 실린 정적 글이라 조회·로딩 상태가 없다. */
export function useGuidePages(topicId: CreationGuideTopicId) {
  return useMemo(() => {
    const topic = findGuideTopic(topicId);
    return { topic, pages: toGuidePages(parseManuscript(topic.manuscript), topic) };
  }, [topicId]);
}
