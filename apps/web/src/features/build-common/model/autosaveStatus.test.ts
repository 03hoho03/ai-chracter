import { describe, expect, it } from "vitest";

import { createAutosaveStatusStore } from "./autosaveStatus";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("createAutosaveStatusStore", () => {
  it("starts idle and goes pending → saving → saved", async () => {
    const store = createAutosaveStatusStore();
    expect(store.getSnapshot()).toBe("idle");
    store.markPending();
    expect(store.getSnapshot()).toBe("pending");
    const save = deferred<string>();
    const tracked = store.track(() => save.promise);
    expect(store.getSnapshot()).toBe("saving");
    save.resolve("ok");
    await expect(tracked).resolves.toBe("ok");
    expect(store.getSnapshot()).toBe("saved");
  });

  it("shows failed and rethrows when the save fails", async () => {
    const store = createAutosaveStatusStore();
    const error = new Error("boom");
    await expect(store.track(() => Promise.reject(error))).rejects.toBe(error);
    expect(store.getSnapshot()).toBe("failed");
  });

  // 저장이 도는 중에 새 편집이 오면 버튼은 계속 진행 중이고, 저장이 끝나면 다음 자동저장을 기다리는 상태로 돌아간다 — 방금 끝난
  // 저장이 새 편집까지 담은 것처럼 "저장됨"을 띄우지 않는다.
  it("keeps saving during a save and falls back to pending for edits made meanwhile", async () => {
    const store = createAutosaveStatusStore();
    const save = deferred<void>();
    const tracked = store.track(() => save.promise);
    store.markPending();
    expect(store.getSnapshot()).toBe("saving");
    save.resolve();
    await tracked;
    expect(store.getSnapshot()).toBe("pending");
  });

  // 앞 저장의 성공이 뒤 저장이 도는 중에 "저장됨"을 띄우지 않고, 마지막에 끝난 저장의 결과가 남는다.
  it("reports the last save's result only after every save has settled", async () => {
    const store = createAutosaveStatusStore();
    const first = deferred<void>();
    const second = deferred<void>();
    const firstTracked = store.track(() => first.promise);
    const secondTracked = store.track(() => second.promise).catch(() => undefined);
    first.resolve();
    await firstTracked;
    expect(store.getSnapshot()).toBe("saving");
    second.reject(new Error("boom"));
    await secondTracked;
    expect(store.getSnapshot()).toBe("failed");
  });

  it("notifies subscribers only when the status changes", async () => {
    const store = createAutosaveStatusStore();
    let calls = 0;
    const unsubscribe = store.subscribe(() => {
      calls += 1;
    });
    store.markPending();
    store.markPending();
    expect(calls).toBe(1);
    await store.track(() => Promise.resolve());
    expect(calls).toBe(3);
    unsubscribe();
    store.markPending();
    expect(calls).toBe(3);
  });
});
