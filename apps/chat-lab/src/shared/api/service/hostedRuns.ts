import { queryOptions, type QueryClient } from "@tanstack/react-query";

import { isRecord } from "@/shared/lib/isRecord";

import type { components } from "../generated";
import { queryClient } from "../queryClient";
import { runKeys } from "../runKeys";
import { isRunBundle } from "../staticBundle";
import { HostedError } from "./hostedFailure";
import { getHostedBundle, getHostedRuns, type HostedRunList, type HostedVersion } from "./serviceClient";

// 측정 서버 쪽 타입은 생성 타입에서 바로 받는다 — `client.ts` 가 이 파일을 불러 쓰므로 서로 부르지 않게 한다.
type RunBundle = components["schemas"]["RunBundle"];
type RunListItem = components["schemas"]["RunListItem"];
type HostedRunItem = HostedRunList["items"][number];

/** 이 웹이 읽는 묶음 계약 판 — 측정 서버 `schemas.py` 의 `CONTRACT_VERSION` 과 같은 값이어야 한다. */
export const CONTRACT_VERSION = 1;

/** 측정 서버가 아는 목록 형식 전부. `Record` 라 측정 서버가 형식을 늘리고 코드젠을 다시 돌리면 여기서 컴파일이 막힌다. */
const RUN_FORMATS = {
  current: true,
  preMessageId: true,
  legacy: true,
} as const satisfies Record<RunListItem["format"], true>;

/**
 * 호스팅 서비스 자원의 캐시 키. 묶음은 런 아래 sha 로 두어, 한 런의 모든 판(`bundlesOf`)이나 모든 런의 묶음(`bundles`)을 한 번에
 * 지운다.
 */
export const hostedRunKeys = {
  all: ["hosted"] as const,
  list: () => [...hostedRunKeys.all, "list"] as const,
  bundles: () => [...hostedRunKeys.all, "bundle"] as const,
  bundlesOf: (runId: string) => [...hostedRunKeys.bundles(), runId] as const,
  bundle: (runId: string, sha256: string) => [...hostedRunKeys.bundlesOf(runId), sha256] as const,
};

/** 목록 표·미리보기·상세 머리가 읽는 그 런의 판 — 최신 판과 살아 있는 판 수. */
export type HostedRunVersion = { latest: HostedVersion; versionCount: number };

/**
 * 이 웹이 읽지 못하는 런. 숨기지 않고 띠에 따로 둔다 — 지울 수 있어야 하고, 기록 한계를 숨기지 않는 것과 같은 원칙이다.
 * - `contract`: 최신 판의 계약 판이 이 웹과 다르다.
 * - `shape`: 목록 칸(`run`)이 측정 서버 목록 한 줄 꼴이 아니거나 그 런 id 가 서비스 런 id 와 다르다.
 * 이름·경로는 목록 칸에 글로 있을 때만 싣는다 — 지우기 확인이 런을 가리킬 때 쓴다.
 */
export type UnreadableRun = {
  runId: string;
  reason: "contract" | "shape";
  latest: HostedVersion;
  versionCount: number;
  storyName: string | undefined;
  path: string | undefined;
};

export type HostedRunsSplit = {
  runs: RunListItem[];
  versions: ReadonlyMap<string, HostedRunVersion>;
  unreadable: UnreadableRun[];
};

/**
 * 런 목록 쿼리. 처음 받기·다시 받기·지우기로만 바뀐다 — 저절로 다시 받으면 런의 최신 sha 가 바뀌어, 이미 캐시된 상세(옛 판)와 새로
 * 고른 턴(새 판)이 한 화면에 섞인다. 다시 시도하지 않는다(세션 끝남·허용 밖은 기다려도 같다). 브라우저가 오프라인이라고 여겨도
 * 요청한다 — 기본값은 그때 요청을 멈춰 화면이 까닭 없이 로딩에 머물고, 보내서 실패하면 네트워크가 끊겼다는 안내가 뜬다.
 */
export function hostedRunsQuery() {
  return queryOptions({
    queryKey: hostedRunKeys.list(),
    queryFn: getHostedRuns,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
    networkMode: "always",
  });
}

/** 서비스 목록을 표에 갈 런·런별 판·읽지 못하는 런으로 나눈다. 들어온 런은 표나 읽지 못하는 런 어느 한쪽에 꼭 한 번 놓인다. */
export function splitHostedRuns(items: ReadonlyArray<HostedRunItem>): HostedRunsSplit {
  const runs: RunListItem[] = [];
  const versions = new Map<string, HostedRunVersion>();
  const unreadable: UnreadableRun[] = [];

  for (const item of items) {
    // 계약 판이 다르면 목록 칸 꼴과 상관없이 계약 판 까닭이다 — 새 계약은 목록 칸 꼴도 바꿀 수 있다.
    const isSameContract = item.latest.contractVersion === CONTRACT_VERSION;
    if (isSameContract && isRunListItem(item.run) && item.run.runId === item.runId) {
      runs.push(item.run);
      versions.set(item.runId, { latest: item.latest, versionCount: item.versionCount });
      continue;
    }
    unreadable.push({
      runId: item.runId,
      reason: isSameContract ? "shape" : "contract",
      latest: item.latest,
      versionCount: item.versionCount,
      storyName: readString(item.run, "storyName"),
      path: readString(item.run, "path"),
    });
  }
  return { runs, versions, unreadable };
}

/**
 * 런 하나의 최신 판 묶음. 목록(캐시에 있으면 그대로)에서 최신 판을 찾아 받는다. 상세·턴·지표가 모두 이것을 읽어, 턴을 여럿 옮겨도
 * 목록과 묶음은 한 번씩만 받는다.
 */
export async function loadHostedBundle(runId: string): Promise<RunBundle> {
  const list = await ensureHostedRuns();
  const item = list.items.find((candidate) => candidate.runId === runId);
  if (item === undefined) throw new HostedError("notFound");
  const { sha256, contractVersion } = item.latest;
  if (contractVersion !== CONTRACT_VERSION) throw new HostedError({ reason: "unsupportedContract", found: contractVersion });

  // 묶음 캐시는 버려지지 않게 두므로(아래) 다른 런의 묶음을 여기서 뺀다 — 메모리에 묶음 하나만 둔다.
  queryClient.removeQueries({
    queryKey: hostedRunKeys.bundles(),
    predicate: (query) => query.queryKey[2] !== runId,
  });
  // sha 로 이름 붙은 내용이라 바뀌지 않는다. 묶음을 직접 구독하는 화면이 없어(상세·턴·지표 쿼리가 읽는다) 기본 GC 면 한 런을 오래
  // 보다 새 턴을 고를 때 큰 묶음을 다시 받는다. 겉모양은 받는 함수 안에서 본다 — 틀린 묶음이 캐시에 남지 않는다.
  return queryClient.fetchQuery({
    queryKey: hostedRunKeys.bundle(runId, sha256),
    queryFn: async () => checkedBundle(await getHostedBundle(runId, sha256), runId),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    networkMode: "always",
  });
}

/**
 * 다시 받기 — 옛 판에서 나온 상세·턴·지표와 묶음을 버리고 보고 있는 목록을 새로 받는다. 묶음은 버려지지 않는 캐시라 빈 상태로
 * 남기지 않게 지우고, 목록만 처음 상태로 되돌려 다시 받는다. 목록 화면에서만 부른다(상세 쿼리가 구독 중이 아니다).
 */
export async function reloadHostedRuns(client: QueryClient): Promise<void> {
  client.removeQueries({ queryKey: runKeys.all });
  client.removeQueries({ queryKey: hostedRunKeys.bundles() });
  await client.resetQueries({ queryKey: hostedRunKeys.list() });
}

/** 묶음을 받으려고 부른 목록의 실패는 목록 실패로 감싼다 — 목록 경로의 404 는 어디서 불렀든 허용 밖 신원이다. */
async function ensureHostedRuns(): Promise<HostedRunList> {
  try {
    return await queryClient.ensureQueryData(hostedRunsQuery());
  } catch (error) {
    throw new HostedError({ reason: "listFailed", listError: error });
  }
}

/**
 * 받은 묶음을 좁힌다. 계약 판을 먼저 본다 — 다른 계약은 묶음 꼴도 바꿀 수 있어, 꼴부터 보면 계약 판이 달라 못 읽는 묶음이 응답 꼴
 * 틀림으로 보인다. 목록의 판만 믿지 않고 받은 묶음의 판도 본다.
 */
function checkedBundle(value: unknown, runId: string): RunBundle {
  if (isRecord(value) && typeof value.contractVersion === "number" && value.contractVersion !== CONTRACT_VERSION) {
    throw new HostedError({ reason: "unsupportedContract", found: value.contractVersion });
  }
  if (!isRunBundle(value) || value.contractVersion !== CONTRACT_VERSION || value.detail.run.runId !== runId) {
    throw new HostedError("badResponse");
  }
  return value;
}

/**
 * 서비스가 올릴 때 받은 측정 서버 목록 한 줄인가 — 측정 서버 스키마의 필수 칸만 본다. 선택 칸은 정적 묶음처럼 측정 서버가 낸 값을
 * 그대로 믿는다(서비스는 이 칸을 고치지 않고 저장한다).
 */
function isRunListItem(value: unknown): value is RunListItem {
  return (
    isRecord(value) &&
    typeof value.runId === "string" &&
    typeof value.path === "string" &&
    (typeof value.group === "string" || value.group === null) &&
    typeof value.format === "string" &&
    Object.hasOwn(RUN_FORMATS, value.format) &&
    typeof value.supported === "boolean" &&
    typeof value.roomId === "string" &&
    typeof value.hasSnapshots === "boolean" &&
    typeof value.hasDump === "boolean" &&
    typeof value.hasChatTurns === "boolean"
  );
}

function readString(record: Readonly<Record<string, unknown>>, key: string): string | undefined {
  const value = record[key];
  return typeof value === "string" ? value : undefined;
}
