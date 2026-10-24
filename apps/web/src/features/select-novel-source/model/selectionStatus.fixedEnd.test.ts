import { describe, expect, it } from "vitest";

import { isFixedEndLost } from "./selectionStatus";

const messages = [
  { id: "a0", role: "assistant" as const, content: "", createdAt: "2026-10-24T00:00:00Z" },
  { id: "u1", role: "user" as const, content: "", createdAt: "2026-10-24T00:00:01.000005Z" },
];

// 고정 끝을 못 찾으면 화면은 지금 방 끝으로 옮겨 저장한다. 키로 자리를 잡을 수 있으면 그럴 필요가 없다 — 서버는 지워진 고정 끝 id 를
// 그대로 받고, 그 뒤 메시지는 새 대화로 보인다.
describe("isFixedEndLost", () => {
  it("고정 끝 메시지가 있으면 잃지 않았다", () => {
    expect(isFixedEndLost(messages, { roomEndMessageId: "u1", roomEndMessageCreatedAt: "2026-10-24T00:00:01.000005Z" })).toBe(false);
  });

  it("고정 끝이 지워졌어도 그 키로 자리를 잡을 수 있으면 잃지 않았다", () => {
    expect(isFixedEndLost(messages, { roomEndMessageId: "gone", roomEndMessageCreatedAt: "2026-10-24T00:00:02Z" })).toBe(false);
  });

  it("고정 끝이 지워졌고 키가 없거나(옛 응답) 메시지에 키가 없으면 잃었다", () => {
    expect(isFixedEndLost(messages, { roomEndMessageId: "gone" })).toBe(true);
    expect(isFixedEndLost(messages, { roomEndMessageId: "gone", roomEndMessageCreatedAt: null })).toBe(true);
    const unkeyed = messages.map(({ createdAt: _createdAt, ...message }) => message);
    expect(isFixedEndLost(unkeyed, { roomEndMessageId: "gone", roomEndMessageCreatedAt: "2026-10-24T00:00:02Z" })).toBe(true);
  });

  it("고정 끝이 없는 판(빈 방)은 잃은 것이 아니다", () => {
    expect(isFixedEndLost(messages, { roomEndMessageId: null, roomEndMessageCreatedAt: null })).toBe(false);
  });
});
