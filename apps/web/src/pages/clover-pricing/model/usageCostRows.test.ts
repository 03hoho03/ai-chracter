import { describe, expect, it } from "vitest";

import { chatAndNovelCostRows } from "./usageCostRows";

const NEW_RESPONSE = {
  chatTurnCost: 10,
  novelEpisodeCost: 80,
  models: [
    { id: "gemini", name: "Gemini", isDefault: true, beta: false, chatTurnCost: 10, novelEpisodeCost: 80 },
    { id: "opus", name: "Claude Opus 5.5", isDefault: false, beta: true, chatTurnCost: 120, novelEpisodeCost: 300 },
  ],
} as const;

// `beta`·최상위 소설 단가가 생기기 전의 서버 응답. 채팅에서 고를 수 없는 Sonnet 행도 실려 있었다.
const OLD_RESPONSE = {
  chatTurnCost: 10,
  models: [
    { id: "gemini", name: "Gemini 3.5 Flash Lite", isDefault: true, chatTurnCost: 10, novelEpisodeCost: 70 },
    { id: "sonnet", name: "Claude Sonnet 4.6", isDefault: false, chatTurnCost: 40, novelEpisodeCost: 200 },
    { id: "opus", name: "Claude Opus 4.6", isDefault: false, chatTurnCost: 65, novelEpisodeCost: 300 },
  ],
} as const;

describe("chatAndNovelCostRows", () => {
  it("새 응답은 모델마다 대화 1턴 한 줄, 그 뒤 최상위 소설 단가 한 줄이다", () => {
    expect(chatAndNovelCostRows(NEW_RESPONSE)).toEqual([
      { key: "chat-gemini", label: "대화 1턴 · Gemini", note: "기본 모델", beta: false, cost: 10 },
      { key: "chat-opus", label: "대화 1턴 · Claude Opus 5.5", note: "무료 대화 없음", beta: true, cost: 120 },
      { key: "novel-episode", label: "소설 1화", note: undefined, beta: false, cost: 80 },
    ]);
  });

  // 소설 화 단가는 상위 모델 행의 값이 아니라 최상위 한 칸이다 — 상위 모델 화 단가를 일반 회원이 살 수 있는 것처럼 싣지 않는다.
  it("소설 1화는 모델 행이 아니라 최상위 칸에서 읽는다", () => {
    const rows = chatAndNovelCostRows({ ...NEW_RESPONSE, novelEpisodeCost: 90 });
    expect(rows.find((row) => row.key === "novel-episode")?.cost).toBe(90);
  });

  it("옛 응답은 실린 모델 행을 그대로 싣고 베타 배지 없이, 소설 1화는 기본 모델 행 값으로 대신한다", () => {
    const rows = chatAndNovelCostRows(OLD_RESPONSE);
    expect(rows.map((row) => row.label)).toEqual([
      "대화 1턴 · Gemini 3.5 Flash Lite",
      "대화 1턴 · Claude Sonnet 4.6",
      "대화 1턴 · Claude Opus 4.6",
      "소설 1화",
    ]);
    expect(rows.every((row) => !row.beta)).toBe(true);
    expect(rows.at(-1)?.cost).toBe(70);
  });

  it("모델 목록이 없는 더 옛 응답은 기본 대화 단가 한 줄로 돌아가고 소설 줄은 싣지 않는다", () => {
    expect(chatAndNovelCostRows({ chatTurnCost: 10 })).toEqual([
      { key: "chat", label: "대화 1턴", note: undefined, beta: false, cost: 10 },
    ]);
  });
});
