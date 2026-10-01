/**
 * `items` 마다 `task` 를 돌리되 동시에 `limit` 개까지만 돌린다. 하나가 실패해도 나머지는 계속 돈다 — 실패 처리는
 * `task` 가 스스로 한다(이 함수는 결과를 모으지 않는다). 모든 작업이 끝나면 풀린다.
 */
export async function runWithConcurrency<T>(
  items: readonly T[],
  limit: number,
  task: (item: T) => Promise<void>,
): Promise<void> {
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const item = items[next];
      next += 1;
      if (item !== undefined) await task(item).catch(() => undefined);
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, () => worker()));
}
