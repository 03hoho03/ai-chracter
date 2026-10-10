/** 가격 응답의 모델 행 하나. `beta` 는 나중에 더한 칸이라 옛 API 응답에는 없다. */
type ModelPricingRow = {
  id: string;
  name: string;
  isDefault: boolean;
  beta?: boolean;
  chatTurnCost: number;
  novelEpisodeCost: number;
};

export type UsageCostRow = {
  key: string;
  label: string;
  /** 이름 아래 보조 글자. */
  note: string | undefined;
  beta: boolean;
  cost: number;
};

/** 쓰임새 목록의 대화·소설 줄. 모델마다 "대화 1턴 · {이름}" 한 줄, 그 뒤 "소설 1화" 한 줄이다.
 *
 * 보조 글자는 기본 모델이면 "기본 모델", 아니면 "무료 대화 없음"이다 — 하루 무료 대화는 기본 모델에만 있어 숫자만 나란히
 * 두면 상위 모델도 무료분 뒤에 깎이는 것으로 읽힌다. `베타` 는 서버의 `beta` 로만 정한다.
 *
 * 소설 화 단가는 응답 최상위의 한 칸이다. 그 칸이 없는 옛 API 응답이면 기본 모델 행의 화 단가로 대신하고, 모델 목록마저
 * 없는 더 옛 응답이면 기본 대화 단가 한 줄만 낸다(소설 줄은 낼 값이 없다). web 과 API 는 따로 배포돼 새 화면이 옛 응답을
 * 받는 구간이 있다. */
export function chatAndNovelCostRows(pricing: {
  chatTurnCost: number;
  models?: readonly ModelPricingRow[];
  novelEpisodeCost?: number;
}): UsageCostRow[] {
  const models = pricing.models ?? [];
  if (models.length === 0) {
    return [{ key: "chat", label: "대화 1턴", note: undefined, beta: false, cost: pricing.chatTurnCost }];
  }

  const rows: UsageCostRow[] = models.map((model) => ({
    key: `chat-${model.id}`,
    label: `대화 1턴 · ${model.name}`,
    note: model.isDefault ? "기본 모델" : "무료 대화 없음",
    beta: model.beta === true,
    cost: model.chatTurnCost,
  }));
  const novelEpisodeCost = pricing.novelEpisodeCost ?? models.find((model) => model.isDefault)?.novelEpisodeCost;
  if (novelEpisodeCost !== undefined) {
    rows.push({ key: "novel-episode", label: "소설 1화", note: undefined, beta: false, cost: novelEpisodeCost });
  }
  return rows;
}
