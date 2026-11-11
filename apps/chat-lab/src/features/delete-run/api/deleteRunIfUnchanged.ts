import type { QueryClient } from "@tanstack/react-query";

import { HostedError } from "@/shared/api/service/hostedFailure";
import { deleteHostedRun, getHostedRuns, type HostedRunList } from "@/shared/api/service/serviceClient";

import { refreshRunEntry } from "../model/deleteCache";

/** 확인 대화가 보인 그 런의 판 — 지우기 직전에 서비스의 지금 값과 견준다. */
export type SeenVersion = { sha256: string; versionCount: number; raw: boolean };

/**
 * 지우기가 끝난 모양. `deletedVersions` 는 서비스가 센 지운 판 수다. 누가 먼저 지웠으면(새로 받은 목록에 없거나 지우기가 404)
 * `alreadyDeleted` 다.
 */
export type DeleteOutcome = { kind: "deleted"; deletedVersions: number } | { kind: "alreadyDeleted" };

/** 지우기를 누른 결과. `changed` 는 대화를 연 사이 그 런에 새 판이 올라와 지우지 않은 것이다(대화는 새 판 수로 다시 그려진다). */
export type DeleteAttempt = DeleteOutcome | { kind: "changed"; versionCount: number };

/**
 * 대화가 보인 판이 지금도 그 런의 판일 때만 지운다. 목록은 저절로 다시 받지 않아, 대화를 연 사이 같은 런에 새 판(원문 포함일 수
 * 있다)이 올라오면 대화는 옛 판 수를 보이는데 서비스는 지금 살아 있는 판을 모두 지운다. 그래서 지우기 직전에 목록을 캐시를 거치지
 * 않고 새로 받아, 그 런의 최신 판·판 수·원문 여부가 대화를 연 때와 같은지 본다.
 */
export async function deleteRunIfUnchanged(queryClient: QueryClient, runId: string, seen: SeenVersion): Promise<DeleteAttempt> {
  const fresh = await freshRuns();
  const item = fresh.items.find((candidate) => candidate.runId === runId);
  if (item === undefined) return { kind: "alreadyDeleted" };
  if (item.latest.sha256 !== seen.sha256 || item.versionCount !== seen.versionCount || item.latest.raw !== seen.raw) {
    refreshRunEntry(queryClient, item);
    return { kind: "changed", versionCount: item.versionCount };
  }
  // 남는 틈은 위 확인과 이 지우기 사이의 밀리초뿐이다 — 서비스의 지우기는 판을 가려 받지 않고 그때 살아 있는 판을 모두 지운다.
  const result = await deleteHostedRun(runId);
  return { kind: "deleted", deletedVersions: result.deletedVersions };
}

/** 목록 요청의 실패는 목록 실패로 감싼다 — 목록 경로의 404 는 지워진 런이 아니라 허용 밖 신원이다. */
async function freshRuns(): Promise<HostedRunList> {
  try {
    return await getHostedRuns();
  } catch (error) {
    throw new HostedError({ reason: "listFailed", listError: error });
  }
}
