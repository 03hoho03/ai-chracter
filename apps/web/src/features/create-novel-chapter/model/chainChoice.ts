import type { NovelChainEstimate, NovelChapterModelId } from "@/entities/novel";

import { toChapterEndAfterModelChange } from "./chapterBoundarySelection";

/** 경계 고르기 목록에서 "남은 대화 전부"(연쇄) 칸의 값. 다른 칸의 값은 메시지 id(UUID)라 겹치지 않는다. */
export const CHAIN_CHOICE_VALUE = "chain";

/**
 * 고른 모델로 "남은 대화 전부"를 보일 견적. 남은 대화가 그 모델의 한 묶음 안에 다 들어가면(묶음 1개 이하) 보이지
 * 않는다 — 그때는 마지막 턴을 고르는 평범한 후보와 같은 일이고, 같은 결정의 칸이 둘이 된다. 견적을 아직 못 받았거나
 * 받지 못했어도(만들 턴이 없음 등) 보이지 않는다.
 */
export function toChainChoice(
  estimates: readonly NovelChainEstimate[] | undefined,
  modelId: NovelChapterModelId,
): NovelChainEstimate | undefined {
  const estimate = estimates?.find((option) => option.model === modelId);
  return estimate !== undefined && estimate.batchCount > 1 ? estimate : undefined;
}

/**
 * 모델을 바꿔 후보를 다시 받은 뒤 골라 둘 칸. "남은 대화 전부"를 골라 두었고 새 모델로도 그 칸이 있으면 그대로 둔다
 * (견적은 모델마다 한 번에 와 있어 다시 받지 않는다). 새 모델로는 그 칸이 없으면 아무것도 고르지 않은 것처럼 새 제안을
 * 골라 둔다. 턴을 골라 두었으면 턴 규칙(`toChapterEndAfterModelChange`) 그대로다.
 */
export function toSelectionAfterModelChange(
  selectedId: string | undefined,
  proposal: Parameters<typeof toChapterEndAfterModelChange>[1],
  hasChainChoice: boolean,
): string | undefined {
  if (selectedId === CHAIN_CHOICE_VALUE) {
    return hasChainChoice ? CHAIN_CHOICE_VALUE : toChapterEndAfterModelChange(undefined, proposal);
  }
  return toChapterEndAfterModelChange(selectedId, proposal);
}
