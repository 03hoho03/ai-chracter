import type { components } from "@ai-character-chat/api-types";

type AdminPromptPlaceholderHint = components["schemas"]["AdminPromptPlaceholderHint"];

/** (채널, 슬롯) → 쓸 수 있는 자리표시자. 서버에 힌트가 없는 칸은 빈 목록이다. */
export type PlaceholderLookup = (channel: string, slot: string) => readonly string[];

const NONE: readonly string[] = [];

/** 초안 응답의 자리표시자 힌트(게시 검사가 쓰는 서버 상수에서 끌어낸 값)로 조회를 만든다. 화면에 따로 사본을 두면 서버 목록이
 * 늘 때 조용히 어긋나므로 이 값만 쓴다. */
export function placeholderLookup(hints: readonly AdminPromptPlaceholderHint[]): PlaceholderLookup {
  const byKey = new Map(hints.map((hint) => [`${hint.channel}:${hint.slot}`, hint.names]));
  return (channel, slot) => byKey.get(`${channel}:${slot}`) ?? NONE;
}
