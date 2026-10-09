import { useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  novelKeys,
  saveReadingPosition,
  sendReadingPositionKeepalive,
  type NovelDetailResponse,
  type NovelReadingPositionRequest,
} from "@/entities/novel";

import { withChapterReadingPosition } from "../lib/readingPositionCache";
import { toRestoreParagraphIndex, type SavedReadingPosition } from "../lib/toRestoreParagraphIndex";

const SAVE_DEBOUNCE_MS = 3000;

type UseReadingPositionOptions = {
  novelId: string;
  chapterId: string;
  revisionId: string;
  paragraphCount: number;
  /** 이 화에 저장된 읽은 자리(`toChapterSavedReadingPosition`). 이 화를 연 적이 없거나 알 수 없으면 없다. */
  saved: SavedReadingPosition | undefined;
  /** `saved` 가 없을 때 서버에도 자리가 없다고 확신하는가. 거짓이면(옛 API 응답) 이용자가 스크롤한 뒤부터 잰다. */
  isAbsenceKnown: boolean;
  /** 이 화를 이미 다 읽었는가(그때는 다시 읽어도 다 읽은 화로 남는다 — 서버도 되돌리지 않는다). */
  wasFinished: boolean;
};

/**
 * 되돌릴 자리의 출처. `saved` 는 되돌릴 자리를 아는 경우(서버에 저장된 자리, 또는 같은 화에서 이미 재고 있던 자리)이고,
 * 나머지 둘은 `toTrackingStart` 의 분류 그대로다 — `none` 은 처음 여는 화, `unknown` 은 그 화의 자리를 싣기 전의
 * API 응답이다.
 */
export type RestoreBasis = "saved" | "none" | "unknown";

/** 지금 문단을 재는 쪽(본문)이 이 화의 읽은 자리와 주고받는 것. */
export type ReadingPositionSession = {
  /** 라우터가 이 화로 오는 이동을 끝냈는가. 한 번 참이면 참으로 남는다 — 되돌리기는 이 뒤에만 한다. */
  hasRouteSettled: boolean;
  /**
   * 본문이 붙을 때 되돌릴 문단과 그 출처. effect 안에서 부른다. 이 화에서 이미 재기 시작했으면(같은 화 안에서 본문을
   * 바꿔 끼운 경우) 마지막으로 잰 문단을 저장된 자리처럼 주고, 아직이면 열 때의 분류를 그대로 준다 — 자리를 모르는
   * 화는 새 본문에서도 계속 첫 이동을 기다리고, 저장된 자리가 있는데 되돌리기를 못 했던 화는 새 본문이 그 자리로 다시
   * 되돌려 본다. 어느 쪽도 서버의 자리를 덮지 않는다 — 다시 되돌리는 자리가 곧 서버의 자리다.
   */
  toRestoreTarget: () => { index: number; basis: RestoreBasis };
  /** 되돌리기가 반영됐거나 이용자가 스스로 움직여 지금 문단을 재기 시작했다. */
  reportTrackingStarted: () => void;
  /** 지금 문단이 바뀌었다. */
  reportParagraph: (index: number) => void;
  /** 마지막 문단에 닿았다. 이미 다 읽은 화면 아무것도 하지 않는다 — 한 번 다 읽은 화는 다시 거짓이 되지 않는다. */
  reportFinished: () => void;
};

function positionKey(body: NovelReadingPositionRequest): string {
  return `${body.revisionId}:${body.paragraphIndex}/${body.paragraphCount}:${body.finished ? 1 : 0}`;
}

/**
 * 화를 읽는 자리를 서버에 남긴다. 화(읽기 화면 마운트) 동안 한 번만 돌고, 지금 문단은 본문 쪽이 재서
 * `ReadingPositionSession` 으로 알려 준다 — 그래서 같은 화 안에서 재는 본문을 바꿔 끼워도 아래 '떠날 때' 처리가
 * 돌지 않고 저장도 끊기지 않는다.
 *
 * - **라우터 대기**: 라우터는 경로가 바뀐 이동 뒤 창을 맨 위로 올리는데, 그 시점은 새 화면이 마운트된 커밋이 아니라
 *   그 뒤 라우터가 이동을 "해결됨"으로 적는 커밋(`resolvedLocation` 갱신 → `onRendered`)이다. 데이터가 캐시에 있으면
 *   읽기 화면이 그보다 먼저 마운트돼, 마운트 직후(다음 프레임)에 되돌리면 곧이어 맨 위로 덮였다(작품 정보 → 이어
 *   읽기에서 실측). 그래서 이동이 해결된 뒤(`hasRouteSettled`)에 본문이 되돌리고 재기 시작한다. 링크마다
 *   `resetScroll: false` 를 다는 길도 있지만, 그러면 읽기 화면으로 오는 모든 길(목차·이전/다음 화·이어 읽기, 그리고
 *   다음에 생길 길)이 그 옵션을 기억해야 하고 브라우저 뒤로 가기에는 달 자리가 없다 — 한 곳(여기)에서 순서를 지키는
 *   쪽이 빠짐이 없다.
 * - **저장 가드**: 본문이 재기 시작하기 전에는 알려 오는 문단이 없어 저장할 것도 없다 — 디바운스 저장·keepalive 모두
 *   나가지 않는다. 저장된 자리와 같은 값은 다시 보내지 않는다.
 * - **저장**: 자리가 바뀌면 3초 뒤 저장한다(스크롤하는 동안 요청이 쏟아지지 않게). 페이지가 숨거나(탭 전환·앱
 *   전환·닫기) 이 화를 떠날 때(다른 화로 옮김 포함) 기다리던 저장을 `keepalive` 로 바로 보낸다 — 그때는 보통 요청이
 *   끊긴다.
 * - **떠날 때**: 저장 응답에 본문이 없어 상세 캐시의 이어 읽기·읽음 표시가 낡는다 — 날아가던 저장과 마지막 저장이
 *   모두 끝난 뒤 상세를 다시 받게 표시해 작품 정보 화면이 돌아왔을 때 맞는 표시를 보게 한다(먼저 다시 받으면 저장
 *   전 값을 받아 낡은 채 남는다). 그 다시 받기가 오기 전에 같은 화로 돌아와도 방금 자리로 열리게, 마지막으로 잰 자리는
 *   떠나는 순간 상세 캐시의 그 화에 먼저 써 둔다(`withChapterReadingPosition`).
 */
export function useReadingPosition({
  novelId,
  chapterId,
  revisionId,
  paragraphCount,
  saved,
  isAbsenceKnown,
  wasFinished,
}: UseReadingPositionOptions): ReadingPositionSession {
  const queryClient = useQueryClient();
  const pendingRef = useRef<NovelReadingPositionRequest | undefined>(undefined);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastKeyRef = useRef<string | undefined>(undefined);
  // 이번에 열어 둔 동안 마지막으로 잰 자리. 떠날 때 상세 캐시에 먼저 써 둔다.
  const lastRecordedRef = useRef<NovelReadingPositionRequest | undefined>(undefined);
  const inflightRef = useRef<Promise<void>>(Promise.resolve());
  const currentIndexRef = useRef<number | undefined>(undefined);
  const isFinishedRef = useRef(wasFinished);
  const hasTrackingStartedRef = useRef(false);
  // 라우터가 이 이동을 끝냈는가(지금 주소가 해결된 주소이고 진행 중인 이동이 없다). 한 번 참이 되면 참으로 남긴다 —
  // 이 화면을 떠나는 다음 이동이 시작돼 거짓이 돼도 되돌리기·재기를 다시 하지 않게.
  const isRouteResolved = useRouterState({
    select: (state) => state.status === "idle" && state.resolvedLocation?.href === state.location.href,
  });
  const [hasRouteSettled, setHasRouteSettled] = useState(isRouteResolved);
  if (isRouteResolved && !hasRouteSettled) setHasRouteSettled(true);

  const restoredIndex = saved === undefined ? 0 : toRestoreParagraphIndex(saved, paragraphCount);

  function cancelTimer() {
    if (timerRef.current === undefined) return;
    clearTimeout(timerRef.current);
    timerRef.current = undefined;
  }

  function takePending(): NovelReadingPositionRequest | undefined {
    cancelTimer();
    const body = pendingRef.current;
    pendingRef.current = undefined;
    return body;
  }

  function record() {
    // 문단이 없는 화는 서버가 자리를 받지 않는다(문단 번호는 문단 수보다 작아야 한다).
    if (paragraphCount === 0) return;
    const currentIndex = currentIndexRef.current;
    if (currentIndex === undefined) return;
    const body = { paragraphIndex: currentIndex, paragraphCount, revisionId, finished: isFinishedRef.current };
    const key = positionKey(body);
    if (key === lastKeyRef.current) return;
    lastKeyRef.current = key;
    lastRecordedRef.current = body;
    pendingRef.current = body;
    cancelTimer();
    timerRef.current = setTimeout(() => {
      const pending = takePending();
      if (pending !== undefined) inflightRef.current = saveReadingPosition(novelId, chapterId, pending);
    }, SAVE_DEBOUNCE_MS);
  }

  function flushKeepalive(): Promise<void> {
    const pending = takePending();
    return pending === undefined ? Promise.resolve() : sendReadingPositionKeepalive(novelId, chapterId, pending);
  }

  useEffect(() => {
    if (!hasRouteSettled) return;
    // 문단이 없는 화는 잴 것도 보낼 것도 없다(`record` 와 같은 이유).
    if (paragraphCount === 0) return;

    // 본문의 같은 effect(자식이라 이보다 먼저 돈다)는 되돌리기를 다음 프레임에 시작하고 문단은 그 뒤에야 알려 온다 —
    // 그래서 아래 초기화와 리스너는 첫 보고보다 앞선다.
    isFinishedRef.current = wasFinished;
    // 저장된 자리와 같은 값은 다시 보내지 않는다.
    if (saved !== undefined) {
      lastKeyRef.current = positionKey({ paragraphIndex: restoredIndex, paragraphCount, revisionId, finished: wasFinished });
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "hidden") void flushKeepalive();
    }

    function handlePageHide() {
      void flushKeepalive();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", handlePageHide);
      const lastRecorded = lastRecordedRef.current;
      if (lastRecorded !== undefined) {
        queryClient.setQueryData<NovelDetailResponse>(novelKeys.detail(novelId), (detail) =>
          withChapterReadingPosition(detail, chapterId, lastRecorded),
        );
      }
      void Promise.all([inflightRef.current, flushKeepalive()]).then(() =>
        queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) }),
      );
    };
    // 화·개정이 바뀌면 읽기 화면이 새로 마운트된다(호출부가 화 id 로 key 를 준다). 저장된 자리는 열 때 한 번만 쓴다 —
    // 라우터가 이동을 끝낸 순간 한 번 돈다(`hasRouteSettled` 는 한 번 참이면 바뀌지 않는다).
  }, [hasRouteSettled]);

  const openingBasis = toOpeningBasis(saved, isAbsenceKnown);

  // 렌더마다 같은 객체를 준다 — 본문 쪽 훅이 이것을 effect 의존에 넣어도 렌더마다 다시 돌지 않게. 메서드가 읽는 값은
  // ref 이거나 화를 연 동안 바뀌지 않는 값(화·개정이 바뀌면 읽기 화면이 새로 마운트된다)이고, 되돌릴 자리를 정하는
  // 값만 의존으로 둔다.
  return useMemo<ReadingPositionSession>(
    () => ({
      hasRouteSettled,
      toRestoreTarget() {
        if (hasTrackingStartedRef.current) return { index: currentIndexRef.current ?? restoredIndex, basis: "saved" };
        return { index: restoredIndex, basis: openingBasis };
      },
      reportTrackingStarted() {
        hasTrackingStartedRef.current = true;
      },
      reportParagraph(index) {
        currentIndexRef.current = index;
        record();
      },
      reportFinished() {
        if (isFinishedRef.current) return;
        isFinishedRef.current = true;
        record();
      },
    }),
    [hasRouteSettled, restoredIndex, openingBasis],
  );
}

/** 화를 열 때의 되돌릴 자리 출처 — 저장된 자리가 있는가, 없다면 없다고 확신하는가. */
function toOpeningBasis(saved: SavedReadingPosition | undefined, isAbsenceKnown: boolean): RestoreBasis {
  if (saved !== undefined) return "saved";
  return isAbsenceKnown ? "none" : "unknown";
}
