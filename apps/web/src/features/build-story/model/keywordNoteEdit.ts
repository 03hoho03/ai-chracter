import { keywordNoteSchema } from "./schema";

/**
 * 트리거 키워드를 하나 더 넣을 때의 거절 이유(넣어도 되면 undefined). 넣은 뒤의 목록을 폼 스키마로 검사하므로
 * 개수·길이·빈 값·정규화 중복의 기준과 문구가 발행 검사와 같다. `keyword` 는 입력칸 값(앞뒤 공백을 지운 값이
 * 들어간다), `existing` 은 그 노트의 지금 키워드들이다.
 */
export function triggerKeywordError(keyword: string, existing: readonly string[]): string | undefined {
  const result = keywordNoteSchema.shape.triggerKeywords.safeParse([...existing, keyword.trim()]);
  return result.success ? undefined : result.error.issues[0]?.message;
}

/** 금지 키워드를 하나 더 넣을 때의 거절 이유 — `triggerKeywordError` 와 같은 방식으로 금지 키워드 목록을 검사한다. */
export function excludeKeywordError(keyword: string, existing: readonly string[]): string | undefined {
  const result = keywordNoteSchema.shape.excludeKeywords.safeParse([...existing, keyword.trim()]);
  return result.success ? undefined : result.error.issues[0]?.message;
}
