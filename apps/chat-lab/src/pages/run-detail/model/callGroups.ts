import type { CallCostView } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";

import { readText } from "./recordFields";

type LooseRecord = Readonly<Record<string, unknown>>;

export type JudgmentSite = {
  callSite: string;
  /** 턴 기록에서 이 call_site 로 기록된 호출(토큰·원가). */
  calls: CallCostView[];
  /** 이 call_site 의 판정 덤프 줄 — 그 턴 판정 덤프 목록에서 1부터 센 순번. */
  dumpIndexes: number[];
};

export type CallGroups = {
  generation: CallCostView[];
  judgment: JudgmentSite[];
  /** 턴 기록에 실린 백그라운드 호출(기억 요약·추출 등). 덤프 줄만 남은 백그라운드 호출은 턴 상세의 백그라운드 덤프 목록에 있다. */
  background: CallCostView[];
  /** 그 밖의 호출(질의 임베딩, 호출 정책 표에 없는 이름 등). */
  other: CallCostView[];
};

/**
 * 생성 묶음 머리의 수 — 그 묶음에 그리는 카드 수다. 턴 기록의 생성 호출마다 카드가 하나이고, 그런 호출이 없으면(턴 기록 파일이
 * 없거나 이 시도에 붙은 행이 없다) 생성 덤프로 그리는 카드 하나가 선다. 턴 기록의 호출만 세면 카드가 보이는데 머리가 0 이 된다.
 * 백그라운드 묶음 머리도 같은 뜻이다(턴 기록 호출 + 덤프 줄 카드). 판정 묶음 머리는 카드가 아니라 call_site 수이고 머리에 그렇게
 * 적는다.
 */
export function generationCardCount(groups: Pick<CallGroups, "generation">): number {
  return Math.max(groups.generation.length, 1);
}

/** 판정 덤프 줄에 call_site 칸이 없을 때 그 줄을 모아 두는 묶음 이름. */
export const MISSING_CALL_SITE = "call_site 없음";

/**
 * 검사기 호출 탭의 묶음 — 생성 · 판정(call_site 별) · 백그라운드 · 그 밖. 종류는 측정 서버가 호출 정책 표로 가른 `kind` 를 그대로
 * 쓴다. 판정 덤프 줄과 판정 호출은 같은 call_site 끼리 한 묶음에 두되 서로 짝짓지는 않는다 — 덤프 줄과 턴 기록의 호출 칸을 잇는
 * 열쇠가 기록에 없다. 판정 묶음은 덤프 줄에서 처음 본 call_site 가 앞이고, 덤프 줄 없이 호출만 있는 call_site 가 그 뒤다.
 */
export function groupCalls(calls: ReadonlyArray<CallCostView>, judgmentDumps: ReadonlyArray<LooseRecord>): CallGroups {
  const sites = new Map<string, JudgmentSite>();
  const siteOf = (callSite: string): JudgmentSite => {
    const existing = sites.get(callSite);
    if (existing) return existing;
    const created: JudgmentSite = { callSite, calls: [], dumpIndexes: [] };
    sites.set(callSite, created);
    return created;
  };

  judgmentDumps.forEach((dump, index) => {
    siteOf(readText(dump, "callSite") ?? MISSING_CALL_SITE).dumpIndexes.push(index + 1);
  });

  const groups: CallGroups = { generation: [], judgment: [], background: [], other: [] };
  for (const call of calls) {
    switch (call.kind) {
      case "generation":
        groups.generation.push(call);
        break;
      case "judgment":
        siteOf(call.callSite).calls.push(call);
        break;
      case "background":
        groups.background.push(call);
        break;
      case "embedding":
      case "other":
        groups.other.push(call);
        break;
      default:
        assertNever(call.kind);
    }
  }
  groups.judgment = [...sites.values()];
  return groups;
}

export type AttemptCalls = {
  groups: CallGroups;
  /** 이 시도에서 그리는 백그라운드 덤프 줄 수 — 턴 상세의 백그라운드 덤프 목록 앞에서부터다. */
  backgroundDumpCount: number;
  /** 고른 시도가 아니라 그리지 않은 그 턴의 판정·백그라운드 덤프 줄 수. */
  heldJudgmentDumps: number;
  heldBackgroundDumps: number;
  /** 호출 탭에 그리는 카드 수 — 탭 머리의 숫자다. */
  cardCount: number;
};

/**
 * 시도 하나의 호출 탭. 턴 기록 호출은 시도마다 붙지만 판정·백그라운드 덤프 줄은 시도가 아니라 턴에 붙어(덤프 줄과 시도를 잇는
 * 열쇠가 기록에 없다), DB 응답으로 고른 시도에서만 그 덤프를 함께 그린다. 고르지 않은 시도에 그리면 서버 앞에서 거부된 시도에도
 * 그 턴 판정이 붙어 보인다. 카드 수는 그린 카드를 그대로 센다 — 생성 묶음은 `generationCardCount`, 판정은 call_site 마다 호출
 * 수(호출 없이 덤프 줄만 있으면 카드 하나), 백그라운드는 호출과 덤프 줄, 그 밖은 호출 수.
 */
export function attemptCalls(
  calls: ReadonlyArray<CallCostView>,
  turnDumps: { judgment: ReadonlyArray<LooseRecord>; backgroundCount: number },
  isSelectedAttempt: boolean,
): AttemptCalls {
  const groups = groupCalls(calls, isSelectedAttempt ? turnDumps.judgment : []);
  const backgroundDumpCount = isSelectedAttempt ? turnDumps.backgroundCount : 0;
  const judgmentCards = groups.judgment.reduce((sum, site) => sum + Math.max(site.calls.length, 1), 0);
  return {
    groups,
    backgroundDumpCount,
    heldJudgmentDumps: isSelectedAttempt ? 0 : turnDumps.judgment.length,
    heldBackgroundDumps: isSelectedAttempt ? 0 : turnDumps.backgroundCount,
    cardCount:
      generationCardCount(groups) + judgmentCards + groups.background.length + backgroundDumpCount + groups.other.length,
  };
}
