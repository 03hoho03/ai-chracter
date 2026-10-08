import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { useSaveNovelBoardLayoutMutation, type NovelBoardViewport } from "@/entities/novel";

import { buildBoardLayoutPayload } from "./boardLayoutPayload";
import { toBoardLayoutSaveFailure } from "./boardLayoutSaveError";
import type { BoardNode } from "./boardNode";

const SAVE_DELAY_MS = 1000;
const SAVE_FAILED_TOAST_ID = "novel-board-layout-save-failed";

type BoardLayoutSnapshot = { nodes: readonly BoardNode[]; viewport: NovelBoardViewport | null };

type UseBoardLayoutSaveOptions = {
  novelId: string;
  /** 상세 `limits.boardLayoutMaxBytes`. */
  maxBytes: number;
  /** 저장하는 순간의 노드와 화면 위치. 디바운스가 끝날 때 읽으므로 렌더 값이 아니라 늘 지금 값을 돌려줘야 한다. */
  read: () => BoardLayoutSnapshot;
  /** 지금 저장해도 되는가(`canSaveBoardLayout`). 아니면 기다리던 저장을 보내지 않고 들고 있다가, 저장해도 되게 되면
   * (인물 목록 도착) 그때 보낸다. */
  canSave: boolean;
};

/**
 * 카드 자리와 화면 위치를 1초 디바운스로 저장한다. 카드를 놓을 때(끌기 끝·키보드 이동)와 화면 이동이 끝날 때 호출부가
 * `schedule()` 을 부른다. 키보드 이동은 누를 때마다 오므로 마지막 한 번만 나간다.
 *
 * - 실패는 고정 `id` 토스트 하나다(반복해도 쌓이지 않고, 눈을 뗀 사이 사라지지 않게 닫을 때까지 남는다). 다음 저장이
 *   성공하면 닫는다. 성공 토스트는 띄우지 않는다.
 * - 크기 초과·재동의는 조용히 건너뛴다(`toBoardLayoutSaveFailure`).
 * - 화면을 떠날 때 기다리던 저장은 버리지 않고 바로 보낸다 — "자동으로 저장돼요"라고 적어 둔 화면이라 마지막 이동을
 *   잃으면 안 된다. 떠난 뒤의 실패는 알릴 화면이 없어 토스트를 띄우지 않고, 남은 실패 토스트도 닫는다.
 */
export function useBoardLayoutSave({ novelId, maxBytes, read, canSave }: UseBoardLayoutSaveOptions) {
  const mutation = useSaveNovelBoardLayoutMutation();
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // 디바운스가 끝나는 순간의 값을 읽어야 해서, 렌더마다 새로 만들어지는 함수들을 ref 로 들고 있는다.
  const readRef = useRef(read);
  readRef.current = read;
  const canSaveRef = useRef(canSave);
  canSaveRef.current = canSave;
  const mutateRef = useRef(mutation.mutateAsync);
  mutateRef.current = mutation.mutateAsync;
  const isMountedRef = useRef(true);
  // 저장할 수 없어 들고 있는 저장이 있는가.
  const hasHeldSaveRef = useRef(false);

  function flush() {
    timerRef.current = undefined;
    if (!canSaveRef.current) {
      hasHeldSaveRef.current = true;
      return;
    }
    hasHeldSaveRef.current = false;
    const { nodes, viewport } = readRef.current();
    const layout = buildBoardLayoutPayload(nodes, viewport, maxBytes);
    if (layout === null) return;
    mutateRef.current({ novelId, layout }).then(
      () => toast.dismiss(SAVE_FAILED_TOAST_ID),
      (error: unknown) => {
        if (!isMountedRef.current || toBoardLayoutSaveFailure(error) === "skip") return;
        toast.error("카드 자리를 저장하지 못했어요. 다시 옮기면 다시 저장해요.", {
          id: SAVE_FAILED_TOAST_ID,
          duration: Infinity,
          closeButton: true,
        });
      },
    );
  }

  function schedule() {
    if (timerRef.current !== undefined) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(flush, SAVE_DELAY_MS);
  }

  useEffect(() => {
    if (canSave && hasHeldSaveRef.current) schedule();
    // 들고 있던 저장을 보낼 시점은 저장해도 되게 된 순간이다.
  }, [canSave]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      toast.dismiss(SAVE_FAILED_TOAST_ID);
      if (timerRef.current === undefined) return;
      clearTimeout(timerRef.current);
      flush();
    };
    // 떠날 때 한 번만 돈다. `flush` 는 ref 로 지금 값을 읽는다.
  }, []);

  return { schedule };
}
