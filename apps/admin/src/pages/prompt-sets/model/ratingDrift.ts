import type { components } from "@ai-character-chat/api-types";

import { PROMPT_LANE_LABELS } from "./lane";
import { PROMPT_MODEL_LABELS } from "./model";

export type AdminPromptRatingDrift = components["schemas"]["AdminPromptRatingDrift"];

const RATING_SCOPE_LABELS = {
  story: "스토리",
  character: "캐릭터",
} satisfies Record<AdminPromptRatingDrift["scope"], string>;

/** 채팅·소설 등급 규칙이 갈린 항목마다 한 문장. 같은 항목은 빼고, 갈린 것이 없으면 빈 목록이다. 서버가 견준 결과를 그대로 읽는다
 * — 어느 레인끼리 견줄지는 서버가 정한다. */
export function ratingDriftLines(items: readonly AdminPromptRatingDrift[] | undefined): string[] {
  return (items ?? [])
    .filter((item) => item.differs)
    .map((item) => {
      const scope = RATING_SCOPE_LABELS[item.scope];
      const other = `${PROMPT_LANE_LABELS[item.otherLane]} · ${PROMPT_MODEL_LABELS[item.otherModel]}`;
      return item.unrenderable
        ? `${scope} 등급 규칙이 ${other} 게시본과 같은지 확인하지 못했어요(렌더되지 않는 본문이 있어요).`
        : `${scope} 등급 규칙이 ${other} 게시본과 달라요.`;
    });
}
