import { describe, expect, it } from "vitest";

// 화면 소스는 문자열로 읽는다 — 이 위젯은 node 환경에서 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
import viewSource from "./PreviewSessionView.tsx?raw";

describe("PreviewSessionView", () => {
  // 미리보기 응답의 id 는 UUID 지만 DB 에 저장되지 않아, 신고를 붙이면 서버가 404 를 낸다.
  // id 형식으로는 저장된 메시지와 구분되지 않으므로 신고 콜백을 아예 넘기지 않는 것으로 막는다.
  it("never wires the chat response report into the builder preview", () => {
    expect(viewSource).toContain("<MessageBubble");
    expect(viewSource).not.toContain("onReport");
  });
});
