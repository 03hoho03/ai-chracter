import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { attendanceBoardQueryOptions, cloverKeys, useClaimAttendanceMutation, type AttendanceBoard } from "@/entities/clover";

import type { ClaimFlow } from "./attendanceView";
import { classifyClaimError, type ClaimErrorKind } from "./claimError";
import { claimReplacesButton, type ClaimFocusTarget } from "./claimFocus";
import { lostClaimOutcome } from "./lostClaimOutcome";

/** 수령 흐름 — 요청, 실패 갈래, 응답을 잃었을 때의 확인까지. 성공(또는 확인 결과 지급됨)이면 흐름을 비워 화면이 판대로
 * 그리게 하고 받은 판으로 `onGranted` 를 부른다(바뀐 칸을 짚는 자리).
 *
 * 결과가 포커스가 있던 자리를 없애면 `onFocusMove` 로 새 자리를 알린다 — 화면이 그리로 포커스를 옮겨 `<body>` 로 떨어지지
 * 않게 하는 신호다. 버튼이 결과·안내 문장으로 바뀌는지는 지급 여부가 아니라 결과 판의 상태로 본다(`claimReplacesButton`).
 *
 * 응답을 잃으면 판을 다시 받아(캐시도 그 판으로 바뀐다) 누르기 직전 판의 마지막 수령일과 견준다. 다시 받기마저 실패하면
 * 확정 실패와 같게 보이고 다시 누르게 한다 — 서버가 하루 한 번만 지급해 다시 눌러도 이중 지급이 없다. */
export function useAttendanceClaim({
  onGranted,
  onFocusMove,
}: {
  onGranted: (board: AttendanceBoard) => void;
  onFocusMove: (target: ClaimFocusTarget) => void;
}) {
  const queryClient = useQueryClient();
  const mutation = useClaimAttendanceMutation();
  const [failure, setFailure] = useState<ClaimErrorKind | null>(null);

  // 확인 중 문장이 버튼 자리를 차지하고 있어서(포커스도 거기 있다), 확인이 어떻게 끝나든 그 문장이 사라진다 — 받았으면 결과
  // 문장으로, 아니면 다시 그려진 수령 버튼으로 포커스를 옮긴다.
  async function confirmLostClaim(lastClaimedOnBefore: string | null) {
    try {
      const board = await queryClient.fetchQuery({ ...attendanceBoardQueryOptions(), staleTime: 0 });
      if (lostClaimOutcome(lastClaimedOnBefore, board) === "notGranted") {
        setFailure("failed");
        onFocusMove("button");
        return;
      }
      void queryClient.invalidateQueries({ queryKey: cloverKeys.balance() });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.ledgers() });
      setFailure(null);
      onGranted(board);
      onFocusMove("message");
    } catch {
      setFailure("failed");
      onFocusMove("button");
    }
  }

  function claim(lastClaimedOnBefore: string | null) {
    setFailure(null);
    mutation.mutate(
      { lastClaimedOnBefore },
      {
        onSuccess: (res) => {
          if (res.granted) onGranted(res.board);
          if (claimReplacesButton({ board: res.board })) onFocusMove("message");
        },
        onError: (error) => {
          const kind = classifyClaimError(error);
          setFailure(kind);
          if (claimReplacesButton({ error: kind })) onFocusMove("message");
          if (kind === "checking") void confirmLostClaim(lastClaimedOnBefore);
        },
      },
    );
  }

  const flow: ClaimFlow = mutation.isPending ? "claiming" : (failure ?? "idle");
  return { flow, claim };
}
