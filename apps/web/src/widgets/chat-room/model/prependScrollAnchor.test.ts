import { MutationObserver, notifyManager, QueryClient, QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { loadOlderKeepingScroll, restorePrependScroll } from "./prependScrollAnchor";

// 화면 컴포넌트는 node 에서 그릴 수 없어(이 위젯은 import 하면 모듈 최상위 localStorage 접근에서 죽는다) React 가 캐시를
// 구독하는 길을 그대로 흉내 낸다 — 쿼리 옵저버 구독을 notifyManager.batchCalls 로 감싸면 React 처럼 렌더 알림이
// setTimeout(0) 뒤로 밀린다. 그 "렌더" 가 첫 메시지 id 가 바뀌었을 때만 레이아웃 이펙트처럼 복원을 부른다.
// 실제 레이아웃(높이)은 메시지 하나를 100px 로 셈한 가짜 스크롤 상자로 대신한다.
const KEY = ["chat-room", "room-1"];
const ROW_HEIGHT = 100;

type Room = { messages: { id: string }[] };

function ids(prefix: string, count: number) {
  return Array.from({ length: count }, (_, index) => ({ id: `${prefix}${index}` }));
}

function flushRender() {
  return new Promise((resolve) => setTimeout(resolve, 10));
}

describe("keeping the reading position when older messages are prepended", () => {
  let queryClient: QueryClient;
  let unsubscribe: () => void;
  let fromBottomRef: { current: number | undefined };
  let scrollArea: { scrollHeight: number; scrollTop: number };
  let renderedFirstId: string | undefined;

  beforeEach(() => {
    queryClient = new QueryClient();
    queryClient.setQueryData<Room>(KEY, { messages: ids("tail", 50) });
    fromBottomRef = { current: undefined };
    scrollArea = { scrollHeight: 50 * ROW_HEIGHT, scrollTop: 0 };
    renderedFirstId = "tail0";
    const observer = new QueryObserver<Room>(queryClient, { queryKey: KEY, enabled: false });
    unsubscribe = observer.subscribe(
      notifyManager.batchCalls(() => {
        const messages = observer.getCurrentResult().data?.messages ?? [];
        scrollArea.scrollHeight = messages.length * ROW_HEIGHT;
        const firstId = messages[0]?.id;
        if (firstId === renderedFirstId) return;
        renderedFirstId = firstId;
        restorePrependScroll(fromBottomRef, scrollArea);
      }),
    );
  });

  afterEach(() => unsubscribe());

  // 훅과 같은 모양 — 받은 페이지를 onSuccess 에서 캐시 앞에 붙인다(요청 때 커서가 아직 첫 메시지일 때만).
  function loadOlder(page: { id: string }[] | Error, beforeSuccess?: () => void) {
    const mutation = new MutationObserver<{ id: string }[], Error, string>(queryClient, {
      mutationFn: () => {
        if (page instanceof Error) return Promise.reject(page);
        beforeSuccess?.();
        return Promise.resolve(page);
      },
      onSuccess: (older, cursorId) => {
        queryClient.setQueryData<Room>(KEY, (prev) =>
          prev && prev.messages[0]?.id === cursorId ? { messages: [...older, ...prev.messages] } : prev,
        );
      },
    });
    return mutation.mutate("tail0").then((messages) => ({ messages }));
  }

  function readFirstMessageId() {
    return queryClient.getQueryData<Room>(KEY)?.messages[0]?.id;
  }

  it("still holds the position when the prepended page is rendered, so the read message stays in place", async () => {
    await loadOlderKeepingScroll(fromBottomRef, scrollArea, () => loadOlder(ids("old", 50)), readFirstMessageId);
    await flushRender();

    // 맨 위(0)에서 눌렀다 — 앞에 50개(5000px)가 붙으면 읽던 tail0 이 그 아래 그대로 보여야 한다.
    expect(scrollArea.scrollHeight).toBe(100 * ROW_HEIGHT);
    expect(scrollArea.scrollTop).toBe(50 * ROW_HEIGHT);
    expect(fromBottomRef.current).toBeUndefined();
  });

  it("drops the position when the request fails", async () => {
    await expect(
      loadOlderKeepingScroll(fromBottomRef, scrollArea, () => loadOlder(new Error("x")), readFirstMessageId),
    ).rejects.toThrow("x");
    expect(fromBottomRef.current).toBeUndefined();
  });

  it("drops the position when nothing was prepended, so a later unrelated change does not jump", async () => {
    await loadOlderKeepingScroll(fromBottomRef, scrollArea, () => loadOlder([]), readFirstMessageId);
    expect(fromBottomRef.current).toBeUndefined();
  });

  it("drops the position when a refetch replaced the head and the page was discarded", async () => {
    await loadOlderKeepingScroll(
      fromBottomRef,
      scrollArea,
      () => loadOlder(ids("old", 50), () => queryClient.setQueryData<Room>(KEY, { messages: ids("shifted", 50) })),
      readFirstMessageId,
    );
    expect(fromBottomRef.current).toBeUndefined();
    await flushRender();
    expect(readFirstMessageId()).toBe("shifted0");
    expect(scrollArea.scrollTop).toBe(0);
  });
});
