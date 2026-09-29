import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";

import { GUIDE_MARKDOWN_ALLOWED_ELEMENTS, GUIDE_MARKDOWN_OPTIONS } from "../config/guideMarkdownOptions";

const ALLOWED_TAGS = new Set<string>(GUIDE_MARKDOWN_ALLOWED_ELEMENTS);

/**
 * 원고 본문 조각이 가이드 렌더러에서 만드는 태그 중 허용 목록 밖의 것을 돌려준다. 원고 형식 검사용이다.
 * 테스트 전용이다 — 앱 코드에서 import 하면 `react-dom/server` 가 가이드 청크에 실린다.
 *
 * 구문마다 정규식을 두지 않고 렌더 결과의 태그 하나로 판정한다 — `_강조_`·`***셋***`·`텍스트↵---` 처럼
 * 정규식이 놓치는 모양도 결국 태그(`em`·`h2`)로 드러나기 때문이다. 렌더러와 같은 옵션에서 허용 목록만 빼고
 * 렌더해 태그를 모은다(렌더러는 목록 밖 요소를 벗겨 버려서 결과만 보면 알 수 없다).
 */
export function findDisallowedTags(source: string): string[] {
  const tags = new Set<string>();
  renderToStaticMarkup(
    createElement(Markdown, {
      ...GUIDE_MARKDOWN_OPTIONS,
      allowedElements: undefined,
      allowElement: (element) => {
        tags.add(element.tagName);
        return true;
      },
      children: source,
    }),
  );
  return [...tags].filter((tag) => !ALLOWED_TAGS.has(tag));
}
