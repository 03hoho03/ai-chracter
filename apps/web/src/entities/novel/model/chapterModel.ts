import type { components } from "@ai-character-chat/api-types";

/** 서버가 이 계정에 허용한 글쓰기 모델 하나와 그 모델의 화 단가. 상위 모델은 허용이 있을 때만 실리고, 기본 모델은
 * 언제나 맨 앞에 있다. 단가는 화 하나의 값이라 화면이 금액으로 쓰지 않는다 — 금액은 서버가 동작마다 계산해 준다. */
export type NovelChapterModel = components["schemas"]["NovelChapterModel"];
export type NovelChapterModelId = NovelChapterModel["id"];
/** 묶음 하나를 다시 만들 때 고를 수 있는 모델 하나 — 그 묶음의 화 수로 서버가 계산한 금액과 고를 수 있는지. */
export type NovelRegenerateOption = components["schemas"]["NovelRegenerateOption"];

/** 확인 화면의 모델 선택 항목 하나. */
export type ChapterModelOption = {
  id: NovelChapterModelId;
  name: string;
  /** 이 동작을 이 모델로 할 때의 클로버. 서버가 계산한 값이고, 모델만으로는 정해지지 않으면(끝 턴을 아직 안 골랐을
   * 때) 없다 — 그때 항목에 금액을 붙이지 않는다. */
  cost: number | undefined;
  /** 고를 수 없는 이유 한 줄. 있으면 항목이 비활성이다. */
  disabledReason: string | undefined;
};

/** 금액이 모델마다 정해진 선택 항목(다시 만들기). 확인 모달은 고른 항목의 금액을 그대로 요청에 싣는다. */
export type PricedChapterModelOption = ChapterModelOption & { cost: number };

/** 서버의 기본 글쓰기 모델. 모델 목록이 비었을 때 요청에 싣는 값이다. */
const DEFAULT_CHAPTER_MODEL: NovelChapterModelId = "gemini";

const INELIGIBLE_REASON_TEXT: Record<NonNullable<NovelRegenerateOption["ineligibleReason"]>, string> = {
  too_many_episodes: "화가 많아 이 모델로는 못 써요",
  too_many_turns: "대화가 길어 이 모델로는 못 써요",
};

/** 모델 선택을 보일지. 고를 것이 하나뿐이면(상위 모델 허용이 없으면) 선택을 그리지 않는다 — 화면이 이 기능 전과
 * 똑같아야 한다. */
export function hasChapterModelChoice(options: readonly ChapterModelOption[]): boolean {
  return options.length > 1;
}

/** 확인 화면을 열 때 골라 둘 모델. 이 소설이 직전에 쓴 모델이 고를 수 있으면 그 모델이고, 아니면 고를 수 있는 첫
 * 모델이다. 고를 수 있는 모델이 없으면 기본 모델이다 — 요청에는 늘 모델을 싣는다. */
export function initialChapterModelId(
  options: readonly ChapterModelOption[],
  lastModelId: NovelChapterModelId | undefined,
): NovelChapterModelId {
  const selectable = options.filter((option) => option.disabledReason === undefined);
  if (lastModelId !== undefined && selectable.some((option) => option.id === lastModelId)) return lastModelId;
  return selectable[0]?.id ?? DEFAULT_CHAPTER_MODEL;
}

/** 묶음 다시 만들기의 서버 목록 → 선택 항목. 맞지 않는 모델은 빼지 않고 비활성 + 이유로 남긴다 — 왜 그 모델이
 * 없는지 이용자가 묻지 않아도 되게. */
export function toRegenerateModelOptions(options: readonly NovelRegenerateOption[]): PricedChapterModelOption[] {
  return options.map((option) => ({
    id: option.model,
    name: option.name,
    cost: option.cost,
    disabledReason: option.eligible ? undefined : toIneligibleReasonText(option.ineligibleReason),
  }));
}

function toIneligibleReasonText(reason: NovelRegenerateOption["ineligibleReason"]): string {
  // 이유 없는 부적격은 계약에 없지만, 그래도 고를 수 없다는 것만은 말한다 — 고르게 두면 서버가 409 로 막는다.
  return reason === null ? "이 모델로는 못 써요" : INELIGIBLE_REASON_TEXT[reason];
}

/** 새 화 만들기의 모델 목록 → 선택 항목. 금액은 끝 턴을 골라야 정해져(후보마다 화 수가 다르다) 항목에 싣지 않는다. */
export function toProposalModelOptions(models: readonly NovelChapterModel[]): ChapterModelOption[] {
  return models.map((model) => ({ id: model.id, name: model.name, cost: undefined, disabledReason: undefined }));
}
