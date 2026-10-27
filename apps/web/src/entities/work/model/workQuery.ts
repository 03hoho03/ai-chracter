/** 서버(`GET /me/works`·`GET /users/{id}/contents`·`GET /me/drafts` 의 `q`)가 받는 검색어 길이 상한. 넘기면 422가
 * 오므로 보내기 전에 여기서 자른다. 내 작품 화면과 스튜디오가 같은 값을 쓴다. */
export const MY_WORKS_QUERY_MAX_LENGTH = 100;

/**
 * 검색어를 서버에 보낼 꼴로 편다: 앞뒤 공백을 걷고, 상한을 넘으면 자르고, 남는 게 없으면 `undefined`(= 검색 안 함,
 * URL에서도 파라미터가 빠진다).
 *
 * 길이는 UTF-16 단위가 아니라 **코드 포인트**로 센다. 서버의 상한은 파이썬 `len`(코드 포인트)이라 단위가 같아야
 * 하고, `String.prototype.slice`로 자르면 이모지 한가운데가 갈려 짝 잃은 서로게이트가 남는데 그 문자열은
 * `encodeURIComponent`가 `URIError`로 던져 요청 자체가 나가지 않는다.
 */
export function normalizeMyWorksQuery(raw: string): string | undefined {
  const cut = Array.from(raw.trim()).slice(0, MY_WORKS_QUERY_MAX_LENGTH).join("").trimEnd();
  return cut === "" ? undefined : cut;
}
