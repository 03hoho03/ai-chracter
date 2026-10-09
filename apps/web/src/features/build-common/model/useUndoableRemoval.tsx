import { useEffect, useRef } from "react";
import { flushSync } from "react-dom";
import { toast } from "sonner";

import { focusRestoredToggle } from "../lib/focusItemToggle";
import { UNDO_TOAST_DURATION_MS, UndoToastButton } from "../ui/UndoToastButton";
import { orderWithPendingRemovals, restoreIndex, type RemovalPlace } from "./removalOrder";

type UndoableRemovalOptions<T extends { id: string }> = {
  /** 지금 목록(폼 값). 열림 키·되돌릴 자리를 이 값의 `id` 로 정한다. */
  getItems: () => readonly T[];
  remove: (index: number) => void;
  /**
   * 지운 값을 그 자리에 다시 넣는다. 필드 배열이면 `insert(index, item, { shouldFocus: false })` 다 — `insert` 는 그 뒤 항목의
   * 오류도 한 칸씩 함께 밀어 오류가 원래 항목에 남는다(배열을 통째로 `setValue` 하면 오류가 옛 인덱스에 남고 모든 행이 다시
   * 마운트된다). 포커스는 이 훅이 머리 줄 토글로 옮기므로 RHF 가 첫 칸으로 보내지 않게 끈다.
   */
  insert: (index: number, item: T) => void;
  /** 그 항목의 열림 키 — 되살린 뒤 머리 줄 토글을 찾는다. */
  openKey: (id: string) => string;
  /** 토스트 문장의 목적어(조사까지, 예: `‘도희’ 엔딩을`). */
  objectPhrase: (item: T) => string;
  /** 되살린 항목이 보이게 하는 준비(예: 꺼진 '고급 설정' 스위치 켜기). 항목을 넣는 커밋과 같은 동기 구간에서 부른다. */
  beforeRestore?: () => void;
};

/**
 * 반복 항목을 묻지 않고 지우는 대신 "…을 지웠어요 · 되돌리기" 토스트(8초)로 같은 값·같은 자리에 되살릴 길을 둔다. 머리 줄의
 * 삭제 버튼이 펼치기 버튼 바로 옆이라 잘못 누르기 쉽고, 지운 결과는 곧바로 자동저장된다.
 *
 * - 삭제마다 토스트를 따로 띄운다. 지우면 아래 카드가 올라와 같은 자리에 다음 삭제 버튼이 서서 연달아 지우기 쉬운데, 토스트
 *   하나를 덮어쓰면 앞의 삭제는 되돌릴 길이 없어진다. 연달아 지운 것끼리는 어떤 차례로 되돌려도 지우기 전 순서로 돌아온다.
 * - 되살린 값은 지운 값 그대로라 폼 값의 `id`(열림 키)가 같고, 열림 기록은 지울 때 지우지 않으므로 펼침도 지우기 전 그대로다.
 * - 되살린 뒤 포커스는 그 항목의 머리 줄 토글이다.
 * - 되돌리기는 이 훅을 부른 컴포넌트가 마운트돼 있는 동안만 둔다 — 언마운트(탭 전환, 엔딩처럼 시작설정 전환으로 목록이 다시
 *   마운트될 때)에 그 토스트들을 닫는다. 다른 화면에서 누르면 무엇이 돌아왔는지 보이지 않고, 넣을 필드 배열도 없다.
 *
 * 포커스를 이웃으로 옮기는 일은 호출부가 `removeWithUndo` 보다 먼저 한다(지울 항목의 이웃을 아는 것은 호출부다).
 */
export function useUndoableRemoval<T extends { id: string }>({
  getItems,
  remove,
  insert,
  openKey,
  objectPhrase,
  beforeRestore,
}: UndoableRemovalOptions<T>) {
  /** 아직 되돌릴 수 있는 삭제 — 토스트 id 별로, 지운 차례대로. 토스트가 닫히면(시간이 다 됐거나 되돌렸거나) 빠진다. */
  const pendingRef = useRef(new Map<string, RemovalPlace & { item: T }>());

  useEffect(() => {
    const pending = pendingRef.current;
    return () => {
      for (const toastId of pending.keys()) toast.dismiss(toastId);
      pending.clear();
    };
  }, []);

  function restore(removed: RemovalPlace & { item: T }) {
    const index = restoreIndex(
      getItems().map((item) => item.id),
      removed,
    );
    if (index === undefined) {
      toast("그 사이 목록이 바뀌어서 되돌리지 않았어요.");
      return;
    }
    // 머리 줄 토글이 생기도록 동기로 커밋한 뒤 포커스한다.
    flushSync(() => {
      beforeRestore?.();
      insert(index, removed.item);
    });
    focusRestoredToggle(openKey(removed.id));
    toast.success(`${objectPhrase(removed.item)} 되돌렸어요.`);
  }

  function removeWithUndo(index: number) {
    const items = getItems();
    const target = items[index];
    if (target === undefined) return;
    const removed = {
      id: target.id,
      order: orderWithPendingRemovals(
        items.map((item) => item.id),
        [...pendingRef.current.values()],
      ),
      item: structuredClone(target),
    };
    remove(index);

    const toastId = `item-remove-undo-${crypto.randomUUID()}`;
    const pending = pendingRef.current;
    pending.set(toastId, removed);
    const forget = () => void pending.delete(toastId);
    toast(`${objectPhrase(removed.item)} 지웠어요.`, {
      id: toastId,
      duration: UNDO_TOAST_DURATION_MS,
      onDismiss: forget,
      onAutoClose: forget,
      action: (
        <UndoToastButton
          onClick={() => {
            forget();
            toast.dismiss(toastId);
            restore(removed);
          }}
        />
      ),
    });
  }

  return removeWithUndo;
}
