import type { components } from "@ai-character-chat/api-types";

/** 장 확인 화면에서 고를 수 있는 글쓰기 모델 하나와 그 모델의 장 생성·재생성 가격. 서버가 소설 상위 모델 허용이
 * 있을 때만 상위 모델을 싣고, 기본 모델은 언제나 맨 앞에 있다. */
export type NovelChapterModel = components["schemas"]["NovelChapterModel"];
export type NovelChapterModelId = NovelChapterModel["id"];

/** 서버의 기본 글쓰기 모델. 모델 목록이 오지 않을 때(이 칸이 생기기 전의 서버) 요청에 싣는 값이다. */
const DEFAULT_CHAPTER_MODEL: NovelChapterModelId = "gemini";

/** 모델 선택을 보일지. 고를 것이 하나뿐이면(상위 모델 허용이 없으면) 선택을 그리지 않는다 — 화면이 이 기능 전과
 * 똑같아야 한다. */
export function hasChapterModelChoice(models: readonly NovelChapterModel[]): boolean {
  return models.length > 1;
}

/** 확인 화면을 열 때 골라 둘 모델. 이 소설이 직전에 쓴 모델이 기본이고(서버가 지금 쓸 수 있는 값으로 바꿔 준다),
 * 그 모델이 목록에 없으면 목록 맨 앞(기본 모델)이다. */
export function initialChapterModelId(
  models: readonly NovelChapterModel[],
  lastModelId: NovelChapterModelId | undefined,
): NovelChapterModelId {
  if (lastModelId !== undefined && models.some((model) => model.id === lastModelId)) return lastModelId;
  return models[0]?.id ?? DEFAULT_CHAPTER_MODEL;
}

/** 고른 모델로 이 장 작업 한 번의 클로버. 목록에 그 모델이 없으면(목록이 오지 않는 서버) `fallbackCost` — 이 기능
 * 전부터 서버가 주던 기본 모델 가격(제안의 `cost`, 상세의 `prices`)이다. 요청의 `expectedCost` 도 이 값이라 화면에
 * 보인 금액과 서버가 대조하는 금액이 같다. */
export function chapterModelCost(
  models: readonly NovelChapterModel[],
  modelId: NovelChapterModelId,
  kind: "generate" | "regenerate",
  fallbackCost: number,
): number {
  const model = models.find((item) => item.id === modelId);
  if (!model) return fallbackCost;
  return kind === "generate" ? model.chapterGenerate : model.chapterRegenerate;
}
