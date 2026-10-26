import type { ApiError } from "@ai-character-chat/api-types";
import { z } from "zod";

import { isApiError } from "@/shared/lib/api/client";

import type { RouteCellKey } from "./schema";

/** 저장 검사 거부의 규칙 이름 → 운영자가 읽는 말. 규칙 목록은 OpenAPI 밖(422 의 `detail`)이라 유니언으로 묶을 수 없어, 모르는
 * 규칙은 원문을 그대로 보인다. */
const ROUTE_RULE_LABELS: Record<string, string> = {
  "unknown-stage": "표에 없는 칸",
  "duplicate-row": "같은 칸 두 번",
  "generation-chain": "생성 행에 체인 지정",
  "generation-call-model": "생성 행은 방 모델만",
  "pair-not-allowed": "허용하지 않는 모델·경로",
  "backend-mismatch": "지금 env 경로와 다름",
  "missing-credentials": "그 경로의 키가 비어 있음",
  "structured-effort": "구조화 깊이 범위 밖",
  "chain-not-published": "그 체인에 게시본 없음",
  "chain-missing-channel": "그 체인 활성본에 필요한 채널 없음",
  "chain-not-in-lane": "그 레인에 없는 체인",
  "lane-out-of-scope": "이 저장에 실을 수 없는 레인",
};

export function routeRuleLabel(rule: string): string {
  return ROUTE_RULE_LABELS[rule] ?? rule;
}

const ruleItemSchema = z.object({
  rule: z.string(),
  message: z.string(),
  row: z.object({ lane: z.string(), roomModel: z.string(), stage: z.string() }),
});

const ruleDetailSchema = z.object({ errors: z.array(ruleItemSchema).min(1) });
const staleDetailSchema = z.object({ rule: z.literal("stale-revision"), message: z.string() });

export type RouteRuleItem = { key: RouteCellKey | null; rule: string; message: string };

/** 저장·되돌리기 실패를 화면이 다루는 꼴로 나눈다.
 * - `rules`: 422 행 검사 거부. 행마다 첫 위반 전부. 지금 코드가 모르는 칸(옛 이력의 내린 값)은 `key` 가 null 이다.
 * - `stale`: 그 사이 다른 저장이 먼저 반영됨(낡은 이력 409, 또는 번호 경쟁 409 의 문자열).
 * - `not-found`: 되돌릴 이력이 없음.
 * - `other`: 그 밖·네트워크. */
export type RouteSaveFailure =
  | { kind: "rules"; items: RouteRuleItem[] }
  | { kind: "stale"; message: string }
  | { kind: "not-found"; message: string }
  | { kind: "other" };

/** `cellKeys` 는 지금 표의 칸 키를 문자열로 찾는 사상이다 — 서버가 준 칸을 `as` 없이 표의 키로 좁힌다. */
export function classifyRouteSaveError(
  error: unknown,
  cellKeys: ReadonlyMap<string, RouteCellKey>,
): RouteSaveFailure {
  if (!isApiError(error)) return { kind: "other" };
  if (error.status === 422) {
    const parsed = ruleDetailSchema.safeParse(error.detail);
    if (!parsed.success) return { kind: "other" };
    return {
      kind: "rules",
      items: parsed.data.errors.map((item) => {
        const key = cellKeys.get(`${item.row.lane}|${item.row.roomModel}|${item.row.stage}`) ?? null;
        return { key, rule: item.rule, message: item.message };
      }),
    };
  }
  if (error.status === 409) {
    const stale = staleDetailSchema.safeParse(error.detail);
    if (stale.success) return { kind: "stale", message: stale.data.message };
    if (typeof error.detail === "string") return { kind: "stale", message: error.detail };
    return { kind: "other" };
  }
  if (error.status === 404) return { kind: "not-found", message: detailText(error) };
  return { kind: "other" };
}

function detailText(error: ApiError): string {
  return typeof error.detail === "string" ? error.detail : error.message;
}
