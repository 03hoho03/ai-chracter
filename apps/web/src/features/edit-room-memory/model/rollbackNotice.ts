/** 되감기 알림("요약이 이전 판으로 돌아갔어요")은 롤백 한 번에 한 번만 띄운다. 무엇을 봤는지는 방별로
 * 브라우저에 남긴다 — 새로고침해도 같은 롤백을 다시 알리지 않고, 롤백 시각이 바뀌면(새 롤백) 다시 알린다.
 *
 * 저장소는 인자로 받는다: 사생활 모드·차단된 사이트 데이터에서는 접근 자체가 던질 수 있어 읽기·쓰기를 모두
 * 삼키고, 그때는 "본 적 없음"으로 취급한다(알림이 한 번 더 뜨는 쪽이 조용히 사라지는 쪽보다 낫다). */
type SeenStorage = Pick<Storage, "getItem" | "setItem">;

function storageKey(roomId: string): string {
  return `memory-rollback-seen:${roomId}`;
}

/** 브라우저 저장소. 접근 자체가 던질 수 있어(사이트 데이터 차단) 여기서 삼킨다. */
export function browserStorage(): SeenStorage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function readSeenRollback(storage: SeenStorage | undefined, roomId: string): string | null {
  try {
    return storage?.getItem(storageKey(roomId)) ?? null;
  } catch {
    return null;
  }
}

export function writeSeenRollback(storage: SeenStorage | undefined, roomId: string, rolledBackAt: string): void {
  try {
    storage?.setItem(storageKey(roomId), rolledBackAt);
  } catch {
    // 저장하지 못하면 다음에 한 번 더 알릴 뿐이다.
  }
}

export function isRollbackUnseen(rolledBackAt: string | null, seenRolledBackAt: string | null): boolean {
  return rolledBackAt !== null && rolledBackAt !== seenRolledBackAt;
}
