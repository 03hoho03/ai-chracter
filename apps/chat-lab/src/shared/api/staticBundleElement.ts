/**
 * 정적 HTML 에 런 묶음을 싣는 `<script type="application/json">` 태그의 id. 내보내기 스크립트(`scripts/staticHtml.mjs`)가 이 파일을
 * Node 로 직접 읽어(타입만 벗겨) 같은 값을 쓴다 — 그래서 이 파일은 아무것도 import 하지 않는다. `@/` 별칭이나 확장자 없는 경로는
 * Node 가 풀지 못한다.
 */
export const STATIC_BUNDLE_ELEMENT_ID = "chat-lab-bundle";
