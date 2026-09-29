import type { Options } from "react-markdown";

/**
 * 원고 본문(예시 블록 밖)에서 그리는 요소. 표·이미지·제목(h3 제외)·강조(`em`)·코드 블록은 없다.
 *
 * - `em` 이 없는 이유: Pretendard 에는 이탤릭 글꼴이 없어 브라우저가 한글을 비스듬히 합성해 깨뜨린다.
 *   지문 표기를 보여 줄 때는 인라인 코드나 채팅 예시 블록을 쓴다.
 * - `pre` 가 없는 이유: 코드 블록은 채팅 예시 블록(백틱 네 개 펜스) 안에서만 쓴다. 형식이 틀린 펜스가
 *   조용히 일반 코드 블록으로 그려져 인용 검사를 빠져나가지 않게, 원고 검사 테스트가 이 목록 밖의 태그를
 *   실패로 본다.
 */
export const GUIDE_MARKDOWN_ALLOWED_ELEMENTS = [
  "p",
  "h3",
  "ul",
  "ol",
  "li",
  "a",
  "strong",
  "code",
  "blockquote",
  "hr",
  "br",
] as const;

/**
 * 가이드 본문 렌더러 옵션. 원고 검사 테스트가 같은 값으로 렌더해 태그를 모은다.
 *
 * - GFM 을 쓰지 않는다: 취소선이 물결표 하나에도 걸려 `10~15턴 사이, 엔딩은 20~25턴` 의 가운데를 긋는다.
 * - `skipHtml`: 원문 HTML(주석 포함)을 글자로 찍지 않고 버린다.
 * - `unwrapDisallowed`: 목록 밖 요소를 만나면 요소만 벗기고 안의 글자는 남긴다(기본값이면 글자까지 사라진다).
 */
export const GUIDE_MARKDOWN_OPTIONS = {
  skipHtml: true,
  allowedElements: GUIDE_MARKDOWN_ALLOWED_ELEMENTS,
  unwrapDisallowed: true,
} satisfies Options;
