import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiErrorObject } from "../client";
import { openChatStream, type ChatStreamRequestPayload } from "./openChatStream";

const eventSchema = z.object({ type: z.literal("token"), delta: z.string() });

const PAYLOAD: ChatStreamRequestPayload = { kind: "send", roomId: "room-1", content: "안녕" };

function stubFetchWith(response: Response) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

async function collect(): Promise<unknown[]> {
  const events: unknown[] = [];
  for await (const event of openChatStream(PAYLOAD, eventSchema)) events.push(event);
  return events;
}

/** 던져진 값을 그대로 받는다 — `rejects.toMatchObject`만으로는 "무엇이 던져졌는가"(ApiErrorObject인지
 * 일반 Error인지)를 같은 호출에서 함께 볼 수 없다. */
async function collectRejection(): Promise<unknown> {
  return collect().then(
    () => null,
    (reason: unknown) => reason,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("openChatStream", () => {
  it("정상 스트림은 data 줄을 이벤트 단위로 흘려보낸다", async () => {
    stubFetchWith(
      new Response('data: {"type":"token","delta":"안"}\n\ndata: {"type":"token","delta":"녕"}\n\n'),
    );

    await expect(collect()).resolves.toEqual([
      { type: "token", delta: "안" },
      { type: "token", delta: "녕" },
    ]);
  });

  // 이 바디가 여기서 `detail`째로 살아 나와야 `isLegalReconsentRequiredError`가 판정할 수
  // 있다. shared는 entities를 import할 수 없으므로(eslint no-restricted-paths) 그 함수가
  // 읽는 세 가지(status 403 · detail이 object · code)를 여기서 직접 고정한다.
  it("403 재동의 바디를 detail째로 던진다", async () => {
    stubFetchWith(
      new Response(JSON.stringify({ detail: { code: "LEGAL_RECONSENT_REQUIRED", kinds: ["terms"] } }), {
        status: 403,
      }),
    );

    const rejection = await collectRejection();

    expect(rejection).toBeInstanceOf(ApiErrorObject);
    expect(rejection).toMatchObject({
      status: 403,
      detail: { code: "LEGAL_RECONSENT_REQUIRED", kinds: ["terms"] },
    });
  });

  it("429 USER_LIMIT 바디를 detail째로 던진다 — 헤더가 없어 여기 말고는 읽을 자리가 없다", async () => {
    stubFetchWith(
      new Response(JSON.stringify({ detail: { code: "USER_LIMIT", retryAfterSeconds: 42, window: "minute" } }), {
        status: 429,
      }),
    );

    const rejection = await collectRejection();

    expect(rejection).toBeInstanceOf(ApiErrorObject);
    expect(rejection).toMatchObject({
      status: 429,
      detail: { code: "USER_LIMIT", retryAfterSeconds: 42, window: "minute" },
    });
  });

  it("파싱되지 않는 바디(프록시의 HTML 502)여도 던지기는 한다", async () => {
    stubFetchWith(
      new Response("<html>502 Bad Gateway</html>", {
        status: 502,
        headers: { "content-type": "text/html" },
      }),
    );

    const rejection = await collectRejection();

    expect(rejection).toBeInstanceOf(Error);
    expect(rejection).toMatchObject({ status: 502, detail: undefined });
  });

  it("200인데 바디가 없으면 바디 파싱 경로를 타지 않는다", async () => {
    stubFetchWith(new Response(null, { status: 200 }));

    const rejection = await collectRejection();

    expect(rejection).toBeInstanceOf(Error);
    expect(rejection).not.toBeInstanceOf(ApiErrorObject);
  });
});
