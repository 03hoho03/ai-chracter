import type { PromptLane } from "../model/lane";
import type { PromptModel } from "../model/model";

/** 레인·모델은 2·3번째 세그먼트 — 초안과 미리보기는 (레인, 모델) 체인마다 따로다. `list()`/`detail(id)`는
 * 레인이 없는 한 엔드포인트(`GET /admin/prompt-sets`)라 레인 밖에 둔다 — 레인별로 쪼개면
 * 한 체인 게시가 자기 사본만 무효화해 나머지 체인의 `isActive` 배지가 낡은 채로 남는다. */
export const promptSetKeys = {
  all: ["promptSets"] as const,
  chain: (lane: PromptLane, model: PromptModel) => [...promptSetKeys.all, lane, model] as const,
  draft: (lane: PromptLane, model: PromptModel) => [...promptSetKeys.chain(lane, model), "draft"] as const,
  preview: (lane: PromptLane, model: PromptModel) => [...promptSetKeys.chain(lane, model), "preview"] as const,
  list: () => [...promptSetKeys.all, "list"] as const,
  detail: (id: string) => [...promptSetKeys.all, "detail", id] as const,
};
