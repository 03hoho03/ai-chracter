import {
  PROMPT_MODEL_LABELS,
  ROUTE_BACKEND_LABELS,
  type AdminPromptRouteAllowedPair,
  type AdminPromptRouteCall,
  type AdminPromptRouteCell,
  type AdminPromptRoutePrice,
  type AdminPromptRoutingResponse,
} from "@/entities/prompt-routing";

import { pairValue, type RouteCellForm } from "./schema";

/** 단가는 단가 표의 값을 반올림 없이 그대로 보인다(0.125 같은 값이 있다). */
export function formatPrice(price: AdminPromptRoutePrice): string {
  return `입 ${price.inputUsdPerMillion} / 출 ${price.outputUsdPerMillion}`;
}

export function formatCachePrice(price: AdminPromptRoutePrice): string {
  return `캐시 읽기 ${price.cachedInputUsdPerMillion} · 캐시 쓰기 ${price.cacheWriteUsdPerMillion}`;
}

export function pairLabel(pair: Pick<AdminPromptRouteAllowedPair, "model" | "backend">): string {
  return `${PROMPT_MODEL_LABELS[pair.model]} · ${ROUTE_BACKEND_LABELS[pair.backend]}`;
}

export function findPair(data: AdminPromptRoutingResponse, value: string): AdminPromptRouteAllowedPair | undefined {
  return data.allowedPairs.find((pair) => pairValue(pair) === value);
}

/** 칸이 고를 수 있는 쌍. 생성 단계는 방 모델로만 부르므로(대화 차감이 방 모델 단가다) 그 방 모델의 쌍뿐이다 — 서버 후보도 같은
 * 규칙으로 거른 목록이라 후보에서 만든다. */
export function selectablePairs(cell: AdminPromptRouteCell): AdminPromptRouteAllowedPair[] {
  return cell.candidates.map((candidate) => ({ kind: cell.kind, model: candidate.model, backend: candidate.backend }));
}

/** 그 쌍을 고르면 그 칸의 호출 위치가 보낼 모델 id·단가. */
export function candidateCalls(cell: AdminPromptRouteCell, value: string): AdminPromptRouteCall[] | undefined {
  return cell.candidates.find((candidate) => pairValue(candidate) === value)?.calls;
}

/** 저장 확인·이력 상세의 한 줄 요약. */
export function describeCellForm(cell: AdminPromptRouteCell, form: RouteCellForm, data: AdminPromptRoutingResponse) {
  if (form.mode === "env") return "행 없음 — env 기본값";
  const pair = findPair(data, form.pair);
  const target = pair === undefined ? form.pair : pairLabel(pair);
  if (cell.kind === "generation") return `방 모델 체인, 경로만 ${target}`;
  const chain = form.chainModel === null ? "체인 없음" : `${PROMPT_MODEL_LABELS[form.chainModel]} 체인`;
  return `${chain} → ${target}`;
}

/** 판정 칸에서 읽을 체인과 부를 모델이 다르면 그 안내 문장, 같으면 null. 서버는 이 조합을 막지 않지만 그 문안은 다른 모델에
 * 맞춰 썼을 수 있다 — 막지 않고 알리기만 한다. */
export function chainCallMismatchText(
  cell: AdminPromptRouteCell,
  form: RouteCellForm | undefined,
  data: AdminPromptRoutingResponse,
): string | null {
  if (form?.mode !== "row" || cell.kind !== "structured" || form.chainModel === null) return null;
  const pair = findPair(data, form.pair);
  if (pair === undefined || pair.model === form.chainModel) return null;
  return `${PROMPT_MODEL_LABELS[form.chainModel]} 체인 문안을 ${PROMPT_MODEL_LABELS[pair.model]}(으)로 불러요 — 그 문안은 다른 모델에 맞춰 썼을 수 있어요`;
}
