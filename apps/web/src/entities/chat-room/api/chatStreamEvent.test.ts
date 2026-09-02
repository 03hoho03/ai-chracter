import { describe, expect, it } from "vitest";

import { chatStreamEventSchema } from "./chat-room";

/**
 * SSE 이벤트 스키마. 이 파일이 있는 이유는 스키마가 **타입의 단일 소스**이기 때문이다 —
 * `ChatStreamEvent`와 `ChatMessage`가 여기서 `z.infer`로 도출되므로, 스키마가 BE와 어긋나면
 * 타입도 함께 어긋나고 컴파일러는 아무것도 못 잡는다. 와이어 모양을 여기서 고정한다.
 *
 * 참조: `apps/api/src/api/chat/schemas.py`의 ChatStreamEvent.
 */
describe("chatStreamEventSchema", () => {
  it("여섯 이벤트 타입을 전부 파싱한다", () => {
    const events: unknown[] = [
      { type: "token", delta: "안녕" },
      { type: "statChange", statId: "s1", newValue: 42 },
      { type: "endingReached", endingId: "e1", epilogue: "끝" },
      { type: "policyWarning", message: "주의" },
      {
        type: "done",
        finalMessage: { id: "m1", role: "assistant", content: "본문", createdAt: "2026-08-29T00:00:00Z" },
      },
      { type: "error", message: "실패" },
    ];

    for (const event of events) {
      expect(chatStreamEventSchema.safeParse(event).success).toBe(true);
    }
  });

  it("endingReached의 epilogue는 null일 수 있다", () => {
    expect(
      chatStreamEventSchema.safeParse({ type: "endingReached", endingId: "e1", epilogue: null }).success,
    ).toBe(true);
  });

  it("done의 이미지 필드는 선택이다 — 스토리 챗에는 없다", () => {
    const withImage = {
      type: "done",
      finalMessage: {
        id: "m1",
        role: "assistant",
        content: "본문",
        createdAt: "2026-08-29T00:00:00Z",
        imageId: "i1",
        imageUrl: "https://r2.example/i1.webp",
      },
    };
    expect(chatStreamEventSchema.safeParse(withImage).success).toBe(true);
  });

  // 이 케이스가 없어서 프로덕션이 2026-08-29부터 깨져 있었다. 위 테스트는 이미지 필드가
  // **있는 경우와 생략된 경우**만 봤는데, 서버가 실제로 보내는 세 번째 모양이 `null`이다
  // (`image_id: uuid.UUID | None = None` → `"imageId": null`). 매칭이 없는 게 정상이므로
  // 이 모양이 사실상 **모든** 응답의 모양이었다.
  it("done의 이미지 필드는 null일 수 있다 — 매칭이 없으면 서버가 null을 보낸다", () => {
    const withoutImage = {
      type: "done",
      finalMessage: {
        id: "m1",
        role: "assistant",
        content: "본문",
        createdAt: "2026-09-02T00:00:00Z",
        imageId: null,
        imageUrl: null,
      },
    };
    expect(chatStreamEventSchema.safeParse(withoutImage).success).toBe(true);
  });

  it("모르는 타입과 필드가 빠진 이벤트는 거부한다 — 이게 `as` 단언과 갈리는 지점이다", () => {
    expect(chatStreamEventSchema.safeParse({ type: "somethingNew", x: 1 }).success).toBe(false);
    expect(chatStreamEventSchema.safeParse({ type: "token" }).success).toBe(false);
    expect(chatStreamEventSchema.safeParse({ type: "statChange", statId: "s1" }).success).toBe(false);
  });
});
