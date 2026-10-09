import { caseFoldKey } from "@/shared/lib/text/caseFoldKey";
import { countCharacters } from "@/shared/lib/text/characterCount";

import { HASHTAG_TOO_LONG_MESSAGE, MAX_HASHTAG_LENGTH } from "./builderLimits";

export const HASHTAG_DUPLICATE_MESSAGE = "이미 넣은 해시태그예요";

/**
 * 입력한 해시태그를 저장할 모양으로 편다 — 앞뒤 공백과 앞에 붙인 `#`(전각 `＃` 포함)를 지운다. 칩이 `#` 을 그려 주므로
 * 값에 `#` 이 남으면 `##태그` 로 보이고, 같은 태그가 `#` 유무로 둘이 된다.
 */
export function normalizeHashtag(input: string): string {
  return input.trim().replace(/^[#＃]+/u, "").trim();
}

/**
 * `normalizeHashtag` 를 거친 태그를 목록에 더해도 되면 undefined, 아니면 거절 이유. 대소문자·유니코드 조합만 다른 태그는 이미 있는 것으로
 * 본다. 개수 상한은 칩 입력이 먼저 막는다.
 */
export function hashtagRefusal(tag: string, existing: readonly string[]): string | undefined {
  if (countCharacters(tag) > MAX_HASHTAG_LENGTH) return HASHTAG_TOO_LONG_MESSAGE;
  const key = caseFoldKey(tag);
  // 정규화 전에 저장된 태그(`#판타지`)도 같은 태그로 본다.
  return existing.some((item) => caseFoldKey(normalizeHashtag(item)) === key) ? HASHTAG_DUPLICATE_MESSAGE : undefined;
}
