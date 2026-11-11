import { useMutation, useMutationState, useQueryClient, type MutationState } from "@tanstack/react-query";

import { describeHostedFailure } from "@/shared/api/service/hostedFailure";
import { hostedRunKeys } from "@/shared/api/service/hostedRuns";
import { isRecord } from "@/shared/lib/isRecord";

import { clearDeletedRunCache, clearIfAlreadyDeleted } from "../model/deleteCache";
import { deleteRunIfUnchanged, type DeleteOutcome, type SeenVersion } from "./deleteRunIfUnchanged";

/** 지우기 뮤테이션 키 — 목록 머리가 대화 밖에서 가장 최근 지우기의 결과를 읽는다. */
const deleteRunKeys = {
  all: [...hostedRunKeys.all, "delete"] as const,
};

/**
 * 런의 모든 판을 지운다 — 대화가 보인 판(`SeenVersion`)이 지금도 그 런의 판일 때만. 끝나면(이미 지워졌어도) 캐시를 정리하고
 * `onDeleted` 를 부른다 — 정리와 알림을 뮤테이션 정의에 두어, 지운 런의 행이 목록에서 빠지며 대화가 사라져도 빠짐없이 돈다. 그 사이
 * 새 판이 올라왔으면 지우지 않고(`changed`) 대화가 새 판 수로 다시 그려진다.
 */
export function useDeleteRun(runId: string, onDeleted: (outcome: DeleteOutcome) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: deleteRunKeys.all,
    mutationFn: (seen: SeenVersion) => deleteRunIfUnchanged(queryClient, runId, seen),
    // 서비스가 지금 받지 못하면 실패로 보이고 다시 누르게 한다 — 오프라인 판단으로 멈춰 두면 "지우는 중"이 까닭 없이 이어진다.
    networkMode: "always",
    onSuccess: (attempt) => {
      if (attempt.kind === "changed") return;
      clearDeletedRunCache(queryClient, runId);
      onDeleted(attempt);
    },
    onError: (error) => {
      if (clearIfAlreadyDeleted(queryClient, runId, error)) onDeleted({ kind: "alreadyDeleted" });
    },
  });
}

/**
 * 가장 최근 지우기의 결과 — 목록 머리의 상태 문장. 상세에서 지우고 목록으로 옮겨 와도 같은 결과를 읽는다. 가장 최근 지우기가 아직
 * 도는 중이거나 실패했으면(실패는 대화 안에 남는다) 없다.
 */
export function useLastDeletion(): DeleteOutcome | undefined {
  const outcomes = useMutationState({ filters: { mutationKey: deleteRunKeys.all }, select: (mutation) => toOutcome(mutation.state) });
  return outcomes.at(-1);
}

function toOutcome(state: MutationState): DeleteOutcome | undefined {
  if (state.status === "success" && isRecord(state.data)) {
    if (state.data.kind === "deleted" && typeof state.data.deletedVersions === "number") {
      return { kind: "deleted", deletedVersions: state.data.deletedVersions };
    }
    if (state.data.kind === "alreadyDeleted") return { kind: "alreadyDeleted" };
    return undefined;
  }
  if (state.status === "error" && describeHostedFailure(state.error, "delete").kind === "notFound") {
    return { kind: "alreadyDeleted" };
  }
  return undefined;
}
