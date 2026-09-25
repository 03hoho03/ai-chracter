import type { PromptLane } from "../model/lane";

/** 레인은 2번째 세그먼트. `list()`/`detail(id)`는
 * 레인이 없는 한 엔드포인트(`GET /admin/prompt-sets`)라 레인 밖에 둔다 — 레인별로 쪼개면
 * 한 레인 게시가 자기 사본만 무효화해 나머지 두 레인의 `isActive` 배지가 낡은 채로 남는다. */
export const promptSetKeys = {
  all: ["promptSets"] as const,
  lane: (lane: PromptLane) => [...promptSetKeys.all, lane] as const,
  draft: (lane: PromptLane) => [...promptSetKeys.lane(lane), "draft"] as const,
  preview: (lane: PromptLane) => [...promptSetKeys.lane(lane), "preview"] as const,
  list: () => [...promptSetKeys.all, "list"] as const,
  detail: (id: string) => [...promptSetKeys.all, "detail", id] as const,
};
