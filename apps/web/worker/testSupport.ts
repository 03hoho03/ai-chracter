/**
 * worker 테스트 전용 헬퍼. `.test.ts`에서만 import하므로 worker 번들에는 들어가지 않는다
 * (`index.ts`가 참조하지 않는 모듈은 묶이지 않는다).
 */

/**
 * `fetch` 목의 첫 인자에서 URL 문자열을 꺼낸다.
 *
 * `String(input)`을 쓰면 안 되는 이유: `fetch`의 시그니처가 `string | URL | Request`인데 `Request`는
 * 쓸 만한 `toString()`이 없어 `"[object Request]"`가 된다. 그 문자열로 `.startsWith(THUMBNAIL_URL)`나
 * `.includes("/contents/")`를 하면 **에러 없이 조용히 false**가 되어, 목이 엉뚱한 응답을 돌려주고
 * 테스트는 그걸 실패가 아니라 "다른 분기"로 읽는다.
 *
 * 지금 worker는 글로벌 `fetch`에 문자열만 넘기지만(`api.ts`의 템플릿 문자열, `ogImage.ts`의 `url`),
 * 목의 파라미터 타입은 `fetch` 시그니처를 따라 넓을 수밖에 없다. 좁히는 대신 세 경우를 다 옳게
 * 처리해서, 나중에 `Request`를 넘기는 호출이 생겨도 테스트가 조용히 빗나가지 않게 한다.
 */
export function fetchUrlOf(input: string | URL | Request): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}
