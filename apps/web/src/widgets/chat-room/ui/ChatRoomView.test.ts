import { describe, expect, it } from "vitest";

// 화면 소스는 문자열로 읽는다 — 이 위젯은 node 환경에서 import 하면 모듈 최상위 `localStorage` 접근에서 죽는다.
import viewSource from "./ChatRoomView.tsx?raw";

const bubbles = viewSource.match(/<MessageBubble\b[\s\S]*?\/>/g) ?? [];

describe("ChatRoomView report menu wiring", () => {
  it("found the message bubbles it checks — zero matches would make the checks below pass vacuously", () => {
    // 저장된 메시지 목록, 엔딩 에필로그, 스트리밍 중 버블 셋이다.
    expect(bubbles).toHaveLength(3);
  });

  // 신고는 서버에 저장된 AI 응답에만 붙는다. 사용자 메시지·임시 버블을 거르는 판정은 `canReportMessage` 가 한다.
  it("passes onReport to exactly one bubble, gated by canReportMessage", () => {
    const withReport = bubbles.filter((bubble) => bubble.includes("onReport"));
    expect(withReport).toHaveLength(1);
    expect(withReport[0]).toMatch(/onReport=\{\s*canReportMessage\(message\)\s*\?/);
  });

  // 에필로그와 스트리밍 버블은 저장된 행이 아니라 화면이 만든 것이라 신고할 id 가 없다.
  it("gives the ending epilogue and the streaming bubble no report action", () => {
    const temporary = bubbles.filter((bubble) => bubble.includes('"ending-epilogue"') || bubble.includes('"streaming"'));
    expect(temporary).toHaveLength(2);
    for (const bubble of temporary) expect(bubble).not.toContain("onReport");
  });
});
