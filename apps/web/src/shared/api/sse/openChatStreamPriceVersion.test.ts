import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { openChatStream, type ChatStreamRequestPayload } from "./openChatStream";

const eventSchema = z.object({ type: z.literal("token"), delta: z.string() });

/** 요청을 열고 fetch 가 받은 본문(없으면 undefined)을 돌려준다. */
async function sentBody(payload: ChatStreamRequestPayload, priceVersion: number | undefined): Promise<unknown> {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(""));
  vi.stubGlobal("fetch", fetchMock);
  // 이벤트는 보지 않는다 — 스트림을 끝까지 열어 요청이 나가게만 한다.
  const events: unknown[] = [];
  for await (const event of openChatStream(payload, eventSchema, { priceVersion })) events.push(event);
  const init = fetchMock.mock.calls[0]?.[1];
  return typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("채팅 요청 본문의 가격 버전", () => {
  it("전송은 화면이 본 가격 버전을 싣는다", async () => {
    const body = await sentBody({ kind: "send", roomId: "r", content: "안녕" }, 3);
    expect(body).toEqual({ content: "안녕", shortcutId: null, priceVersion: 3 });
  });

  it("편집은 화면이 본 가격 버전을 싣는다", async () => {
    const body = await sentBody({ kind: "edit", roomId: "r", messageId: "m", content: "고침" }, 3);
    expect(body).toEqual({ content: "고침", priceVersion: 3 });
  });

  it("미리보기 전송은 화면이 본 가격 버전을 싣는다", async () => {
    const body = await sentBody({ kind: "preview-send", previewSessionId: "p", content: "안녕" }, 3);
    expect(body).toEqual({ content: "안녕", shortcutId: null, priceVersion: 3 });
  });

  it("재생성은 가격 버전이 있을 때만 그 칸 하나짜리 본문을 보낸다", async () => {
    expect(await sentBody({ kind: "regenerate", roomId: "r" }, 3)).toEqual({ priceVersion: 3 });
    expect(await sentBody({ kind: "regenerate", roomId: "r" }, undefined)).toBeUndefined();
  });

  it("가격 버전을 모르면(가격표를 아직 못 받았거나 옛 서버) 칸을 싣지 않는다", async () => {
    const body = await sentBody({ kind: "send", roomId: "r", content: "안녕" }, undefined);
    expect(body).toEqual({ content: "안녕", shortcutId: null });
  });
});
