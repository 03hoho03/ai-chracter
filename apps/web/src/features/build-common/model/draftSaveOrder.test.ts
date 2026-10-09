import { MutationObserver, QueryClient, onlineManager } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CONTENT_DRAFT_SAVE_TIMEOUT_MS,
  contentDraftSaveOptions,
  type ContentDraftPayload,
  type NovelPermission,
} from "@/entities/content";

import { createNovelPermissionSync } from "./novelPermissionSync";

function payloadWith(novelPermission: NovelPermission): ContentDraftPayload {
  return {
    name: "루나",
    oneLiner: "",
    thumbnailAssetId: null,
    intro: "",
    exampleDialogues: [],
    characterPrompt: "",
    playguide: null,
    situationalImages: [],
    description: "",
    genreId: null,
    target: null,
    hashtags: [],
    visibility: "private",
    novelPermission,
  };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 서버의 초안 PATCH 를 흉내 낸다: 요청이 들어오면 저장된 값을 읽고, 처리가 끝날 때 읽은 값과 다를 때만 쓴다(같으면 그 칸은
 * UPDATE 에 실리지 않는다). 잠금이 없으니 두 요청이 겹치면 둘 다 같은 옛 값을 읽는다. 허락 칸을 실은 첫 요청을 더 느리게 해
 * 겹쳤을 때 앞 요청이 나중에 끝나게 한다.
 */
function fakeServer(initial: NovelPermission) {
  const server = { value: initial, started: [] as (NovelPermission | undefined)[] };
  let calls = 0;
  async function save(payload: ContentDraftPayload) {
    const read = server.value;
    server.started.push(payload.novelPermission ?? undefined);
    calls += 1;
    await sleep(calls === 1 ? 30 : 5);
    if (payload.novelPermission != null && payload.novelPermission !== read) server.value = payload.novelPermission;
    return payload;
  }
  return { server, save };
}

describe("draft saves", () => {
  afterEach(() => {
    onlineManager.setOnline(true);
    vi.useRealTimers();
  });

  // 오프라인에서 다른 값으로 바꿨다가 원래 값으로 되돌린 뒤 다시 연결된 경우. 멈춰 있던 저장 둘이 함께 재개되면 서버에는 중간
  // 값이 남고, 그 뒤 저장은 허락 칸을 빼므로 고쳐지지 않는다.
  it("reach the server one after another, so the last value picked offline is the one kept", async () => {
    const queryClient = new QueryClient();
    queryClient.mount();
    const { server, save } = fakeServer("private");
    const sync = createNovelPermissionSync("private");
    const send = (payload: ContentDraftPayload) =>
      new MutationObserver(queryClient, contentDraftSaveOptions(save, "draft-1")).mutate(sync.prepare(payload));

    onlineManager.setOnline(false);
    const first = send(payloadWith("forbidden"));
    const second = send(payloadWith("private"));
    onlineManager.setOnline(true);
    await Promise.all([first, second]);

    expect(server.started).toEqual(["forbidden", "private"]);
    expect(server.value).toBe("private");

    // 다른 칸만 고친 다음 저장은 허락 칸을 빼고, 서버 값은 마지막으로 고른 값 그대로다.
    await send(payloadWith("private"));
    expect(server.started.at(-1)).toBeUndefined();
    expect(server.value).toBe("private");
    queryClient.unmount();
  });

  // 응답이 오지 않는 요청이 같은 초안의 뒤 저장(발행 직전 저장 포함)을 끝없이 붙잡지 않는다.
  it("give up on a request that never answers, so the next save of the same draft still goes out", async () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient();
    queryClient.mount();
    const started: string[] = [];
    // 서버가 응답하지 않는 요청. 끊기 신호를 받으면 그때 실패한다(axios 가 `signal` 을 받아 하는 일과 같다).
    const hang = (name: string, signal: AbortSignal) =>
      new Promise<string>((_, reject) => {
        started.push(name);
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      });
    const answer = (name: string) => {
      started.push(name);
      return Promise.resolve(name);
    };
    const options = contentDraftSaveOptions(
      (name: string, signal: AbortSignal) => (name === "stuck" ? hang(name, signal) : answer(name)),
      "draft-1",
    );

    // 실패는 시계를 움직이는 도중에 나므로 결과를 미리 받아 둔다(안 그러면 처리되지 않은 거부가 된다).
    const stuck = new MutationObserver(queryClient, options).mutate("stuck").then(
      () => "answered",
      (error: unknown) => (error instanceof Error ? error.message : "failed"),
    );
    const next = new MutationObserver(queryClient, options).mutate("next");
    // 요청이 출발할 때까지 시계를 움직이지 않고 대기 중인 마이크로태스크만 비운다.
    await vi.advanceTimersByTimeAsync(0);
    expect(started).toEqual(["stuck"]);

    await vi.advanceTimersByTimeAsync(CONTENT_DRAFT_SAVE_TIMEOUT_MS - 1);
    expect(started).toEqual(["stuck"]);

    await vi.advanceTimersByTimeAsync(1);
    await expect(stuck).resolves.toBe("aborted");
    await expect(next).resolves.toBe("next");
    expect(started).toEqual(["stuck", "next"]);
    queryClient.unmount();
  });

  it("of different drafts do not wait for each other", async () => {
    const queryClient = new QueryClient();
    queryClient.mount();
    const started: string[] = [];
    let release: () => void = () => {};
    const request = (name: string) =>
      new Promise<string>((resolve) => {
        started.push(name);
        if (name === "first") release = () => resolve(name);
        else resolve(name);
      });

    const first = new MutationObserver(queryClient, contentDraftSaveOptions(request, "draft-1")).mutate("first");
    const other = new MutationObserver(queryClient, contentDraftSaveOptions(request, "draft-2")).mutate("other");

    await expect(other).resolves.toBe("other");
    expect(started).toEqual(["first", "other"]);
    release();
    await first;
    queryClient.unmount();
  });
});
