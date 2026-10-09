import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { novelKeys, type NovelPublicationStatus } from "@/entities/novel";
import { webnovelKeys } from "@/entities/webnovel";
import { apiClient } from "@/shared/api/client";

import { toPublishFailure, type PublishFailure } from "../model/publishFailure";

/** 공개 진행. `checking` 은 몇 번째 요청을 기다리는가(1부터), `failed` 는 멈춘 까닭이다. */
export type PublishRunState =
  | { kind: "idle" }
  | { kind: "checking"; current: number; total: number }
  | { kind: "failed"; failure: PublishFailure };

/** 노벨 공개를 화 하나씩 차례로 보낸다(`POST /novels/{id}/publication` — 요청 하나가 화 하나다). 요청마다 응답한 공개
 * 상태를 캐시에 써서 화면이 "확인 중 · n/N화"와 함께 지금까지 공개한 범위를 그린다. 하나가 실패하면 거기서 멈춘다 —
 * 앞 화까지는 공개된 채 남는다. 실패하면 공개 상태를 다시 받는다(거절이면 마지막 심사, 낡았으면 바뀐 상태를 그린다).
 *
 * 화면을 떠나도 보내던 요청은 끝까지 간다(서버가 그 화까지 공개한다). 다만 다음 요청은 이 훅을 쓰는 화면이 남아 있을
 * 때만 이어 간다 — 떠난 화면이 남은 화를 몰래 계속 공개하지 않게. 진행 중에 다시 부르면 무시한다.
 *
 * 공개한 글은 노벨 화면의 캐시(목록·작품 정보·화)를 낡게 하므로 끝나면 함께 버린다. */
export function usePublishNovelRun(novelId: string) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<PublishRunState>({ kind: "idle" });
  const isRunningRef = useRef(false);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  async function run(requests: readonly (string | null)[]): Promise<boolean> {
    if (isRunningRef.current || requests.length === 0) return false;
    isRunningRef.current = true;
    try {
      for (const [index, chapterId] of requests.entries()) {
        if (index > 0 && !isMountedRef.current) return false;
        setState({ kind: "checking", current: index + 1, total: requests.length });
        try {
          const { data } = await apiClient.post<NovelPublicationStatus>(`/novels/${novelId}/publication`, { chapterId });
          queryClient.setQueryData(novelKeys.publication(novelId), data);
        } catch (error) {
          setState({ kind: "failed", failure: toPublishFailure(error) });
          void queryClient.invalidateQueries({ queryKey: novelKeys.publication(novelId) });
          return false;
        }
      }
      setState({ kind: "idle" });
      return true;
    } finally {
      isRunningRef.current = false;
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.all });
    }
  }

  return { state, run, clearFailure: () => setState({ kind: "idle" }) };
}
