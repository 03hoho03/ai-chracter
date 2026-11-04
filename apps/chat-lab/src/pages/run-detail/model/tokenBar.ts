import type { CallCostView } from "@/shared/api/client";

/** 토큰 막대의 칸 — 이 순서로 잇는다. */
export const TOKEN_PARTS = ["cacheRead", "cacheWrite", "newInput", "output"] as const;
export type TokenPart = (typeof TOKEN_PARTS)[number];

export type TokenSegment = {
  part: TokenPart;
  /** 기록되지 않았으면 undefined — 0 토큰과 갈린다. */
  tokens: number | undefined;
  /** 막대 전체 길이(네 칸 토큰의 합)에 대한 몫(0~1). */
  ratio: number;
};

export type TokenBarView = { kind: "missing" } | { kind: "bar"; segments: TokenSegment[]; total: number };

type CallTokens = Pick<CallCostView, "newInputTokens" | "cachedTokens" | "cacheWriteTokens" | "outputTokens">;

/**
 * 호출 하나의 토큰 막대. 새 입력은 측정 서버가 낸 값(입력 전체에서 캐시 읽기·쓰기를 뺀 몫, 단가표가 입력 정가를 곱하는 몫)을 그대로
 * 쓴다. 입력 토큰이 기록되지 않은 호출은 새 입력도 비어 막대를 그리지 않는다(`missing`) — 원가 계산도 이 호출을 "토큰 없음"으로
 * 센다. 나머지 칸이 비어 있으면 길이 0 이고 칸의 토큰 수도 비워 둔다.
 */
export function describeTokenBar(call: CallTokens): TokenBarView {
  const newInput = call.newInputTokens;
  if (newInput === null) return { kind: "missing" };
  const cacheRead = call.cachedTokens ?? undefined;
  const cacheWrite = call.cacheWriteTokens ?? undefined;
  const output = call.outputTokens ?? undefined;
  const counts = { cacheRead, cacheWrite, newInput, output } satisfies Record<TokenPart, number | undefined>;
  const total = (cacheRead ?? 0) + (cacheWrite ?? 0) + newInput + (output ?? 0);

  return {
    kind: "bar",
    total,
    segments: TOKEN_PARTS.map((part) => {
      const tokens = counts[part];
      return { part, tokens, ratio: total > 0 && tokens !== undefined ? tokens / total : 0 };
    }),
  };
}
