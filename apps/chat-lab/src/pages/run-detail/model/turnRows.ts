import type { AttemptDetail, DriverStatChange, ReplyFlagsView, StatSeries, TurnSummary } from "@/shared/api/client";
import { formatCount } from "@/shared/lib/formatNumber";

import { REPLY_FLAG_LABELS } from "./detailLabels";
import { defaultSlots, lineCandidates } from "./statLines";

/**
 * 스탯 Δ 점의 색. 보이는 스탯은 상태 타임라인에서 선을 받은 자리의 색(한 차트에 선은 셋까지 — 고르지 않으면 계열 순서대로 앞의
 * 셋)이고, 선 자리에 없는 보이는 스탯은 선이 없어 `other`, 숨김 스탯은 네 번째 색을 얻지 않고 `hidden` 이다.
 */
export type StatTone = "series-1" | "series-2" | "series-3" | "other" | "hidden";

export type StatDelta = {
  name: string;
  /** 변화량. 그 턴이 시작한 값을 기록으로 알 수 없으면 undefined — 바뀐 뒤 값만 안다. */
  delta: number | undefined;
  /** 그 턴이 시작한 값. 모르면 undefined. */
  before: number | undefined;
  /** 바뀐 뒤 값. */
  after: number;
  tone: StatTone;
};

/** 턴 목록 한 줄의 플래그 — 좁은 열에 맞춰 한 글자 약자로 적고, 온 이름은 마우스를 올리면·읽기 프로그램이 읽는다. */
export type TurnFlag = {
  key: FlagKey;
  abbr: string;
  label: string;
  isDanger: boolean;
};

export type Utterance = { kind: "user"; text: string } | { kind: "shortcut"; name: string } | { kind: "none" };

/**
 * 턴 목록 행의 응답 한 줄. 응답이 없으면 빈칸 대신, 받은 칸의 모양만으로 정해지는 까닭을 싣는다. 위에서부터 먼저 맞는 것이다.
 * - `reply`: 고른 시도의 응답 앞부분(측정 서버가 앞 200자를 준다). 실패 문장이 함께 있어도 응답이 먼저다.
 * - `failure`: 보일 응답 없이 실패 문장이 있다 — 그 문장. 응답이 교체됐어도 이것이 먼저다(교체 표지는 행에 따로 선다).
 *   `isLost` 는 측정 서버가 이 턴을 유실(응답도 교체 줄도 없음)로 본 것이다 — 교체 줄이 응답을 냈거나 공백뿐인 응답이 왔으면
 *   실패 문장이 있어도 거짓이라, 행이 "응답 없음"이라고 하지 않는다.
 * - `blankHead`: 측정 서버가 주는 앞부분(앞 200자)이 공백뿐이고 그 뒤에 글이 이어진다 — 행에 보일 앞부분이 없지만 빈 응답은 아니다.
 *   응답이 교체됐어도 이것이 먼저다(고른 시도에 응답이 있고, 교체 표지는 행에 따로 선다).
 * - `replaced`: 고른 시도에 보일 응답이 없지만(비었거나 공백뿐) 재생성·수정한 줄이 응답을 냈다 — 유실이 아니다.
 * - `blank`: 응답이 왔는데 공백뿐이다.
 * - `none`: 응답도 실패 문장도 없다.
 *
 * 글은 줄바꿈·탭·겹친 공백을 빈칸 하나로 접어 한 줄로 싣는다.
 */
export type ReplyLine =
  | { kind: "reply"; text: string }
  | { kind: "failure"; text: string; isLost: boolean }
  | { kind: "replaced" }
  | { kind: "blank" }
  | { kind: "blankHead" }
  | { kind: "none" };

export type TurnRow = {
  turn: number;
  utterance: Utterance;
  reply: ReplyLine;
  attemptCount: number;
  isSupplemented: boolean;
  isReplaced: boolean;
  deltas: StatDelta[];
  flags: TurnFlag[];
};

/** 턴 목록에 보이는 플래그 넷과 그 순서·약자. 나머지 지표(질문·청유, 장면 열림 등)는 검사기 지표 탭에서 본다. */
const ROW_FLAGS = [
  { key: "truncated", abbr: "절" },
  { key: "selfCopy", abbr: "복" },
  { key: "labelLeak", abbr: "라" },
  { key: "broken", abbr: "깨" },
] as const;

type FlagKey = (typeof ROW_FLAGS)[number]["key"];

/** 선 자리 순서의 선 색 — 자리 k 가 이 목록의 k 번째 색이다. */
export const SERIES_TONES = ["series-1", "series-2", "series-3"] as const;

/**
 * 런 상세 응답의 턴 요약을 턴 목록 행으로. 플래그는 턴 요약에 실린 그 턴의 응답 지표에서 온다 — 런 지표 응답을 기다리지 않고,
 * 응답이 없어 지표 표본에서 빠진 턴은 플래그가 없다.
 *
 * 보이는 스탯 Δ 는 드라이버 줄(`driverStatChanges`, 이름 키)에서 측정 서버가 낸 변화량을, 숨김 스탯 Δ 는 턴 기록
 * (`recordedStatChanges`)의 전후 차를 쓴다. 턴 기록의 보이는 스탯은 드라이버 줄과 같은 변화라 다시 싣지 않는다.
 */
export function buildTurnRows(
  turns: ReadonlyArray<TurnSummary>,
  series: ReadonlyArray<StatSeries>,
  slots: ReadonlyArray<string> = defaultSlots(series),
): TurnRow[] {
  const tones = seriesTones(series, slots);

  return turns.map((summary) => ({
    turn: summary.turn,
    utterance: utteranceOf(summary),
    reply: replyLineOf(summary),
    attemptCount: summary.attemptCount,
    isSupplemented: summary.supplemented,
    isReplaced: summary.replaced,
    deltas: [...visibleDeltas(summary.driverStatChanges, tones), ...hiddenDeltas(summary)],
    flags: rowFlags(summary.flags),
  }));
}

/**
 * 대화 머리의 Δ 칩. 고른 시도는 턴 목록 행과 같은 Δ 이고, 고르지 않은 시도는 그 시도의 드라이버 줄 변화만 보인다 — 숨김 스탯을
 * 싣는 턴 기록은 고른 시도의 것만 턴 요약에 있다.
 */
export function attemptDeltas(
  row: TurnRow | undefined,
  attempt: AttemptDetail | undefined,
  tones: ReadonlyMap<string, StatTone>,
): StatDelta[] {
  if (attempt !== undefined && !attempt.selected) return visibleDeltas(attempt.driverStatChanges, tones);
  return row?.deltas ?? [];
}

/**
 * Δ 칩·읽기 프로그램에 적을 변화량. 오르내림은 색이 아니라 부호와 숫자로만 말한다. 시작 값을 몰라 변화량이 없으면 "Δ 모름" —
 * 바뀐 뒤 값을 변화량 자리에 적지 않는다.
 */
export function formatStatDelta(delta: StatDelta): string {
  return formatDeltaValue(delta.delta);
}

/** 변화량 하나를 부호 숫자로 — 모르면 "Δ 모름". 타임라인 툴팁도 같은 모양으로 적는다. */
export function formatDeltaValue(delta: number | undefined): string {
  if (delta === undefined) return "Δ 모름";
  if (delta > 0) return `+${formatCount(delta)}`;
  if (delta < 0) return `−${formatCount(-delta)}`;
  return "0";
}

/** 보이는 스탯 이름 → 선 색. 타임라인의 선 자리(`slots`, 스탯 id) k 에 선 스탯이 선 색 k 를 받는다. */
export function seriesTones(
  series: ReadonlyArray<StatSeries>,
  slots: ReadonlyArray<string> = defaultSlots(series),
): ReadonlyMap<string, StatTone> {
  return new Map(
    lineCandidates(series).map((entry) => {
      const slot = slots.indexOf(entry.id);
      return [entry.name, SERIES_TONES[slot] ?? "other"];
    }),
  );
}

function utteranceOf(summary: TurnSummary): Utterance {
  if (summary.userText != null && summary.userText !== "") return { kind: "user", text: summary.userText };
  if (summary.shortcut != null) return { kind: "shortcut", name: summary.shortcut };
  return { kind: "none" };
}

function replyLineOf(summary: TurnSummary): ReplyLine {
  const reply = foldLine(summary.replyHead);
  if (reply !== "") return { kind: "reply", text: reply };
  const failure = foldLine(summary.failure ?? "");
  if (failure !== "") return { kind: "failure", text: failure, isLost: summary.lost };
  if (summary.replyLength > summary.replyHead.length) return { kind: "blankHead" };
  if (summary.replaced) return { kind: "replaced" };
  return summary.replyLength > 0 ? { kind: "blank" } : { kind: "none" };
}

/** 줄바꿈·탭·겹친 공백을 빈칸 하나로 접고 앞뒤 공백을 뗀다. */
function foldLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** 드라이버 줄의 `value` 는 바뀐 뒤 값이라 Δ 로 쓰지 않는다 — 변화량은 측정 서버가 낸 `delta` 다. */
function visibleDeltas(changes: ReadonlyArray<DriverStatChange>, tones: ReadonlyMap<string, StatTone>): StatDelta[] {
  return changes.map((change) => ({
    name: change.name,
    delta: change.delta ?? undefined,
    before: change.before ?? undefined,
    after: change.value,
    tone: tones.get(change.name) ?? "other",
  }));
}

function hiddenDeltas(summary: TurnSummary): StatDelta[] {
  return summary.recordedStatChanges.flatMap((change) => {
    if (change.hidden !== true || change.before == null || change.after == null) return [];
    return [
      {
        name: change.name ?? change.id,
        delta: change.after - change.before,
        before: change.before,
        after: change.after,
        tone: "hidden" as const,
      },
    ];
  });
}

function rowFlags(flags: ReplyFlagsView | null): TurnFlag[] {
  if (flags === null) return [];
  return ROW_FLAGS.filter(({ key }) => isRaised(flags, key)).map(({ key, abbr }) => ({
    key,
    abbr,
    label: REPLY_FLAG_LABELS[key],
    isDanger: key === "broken",
  }));
}

function isRaised(flags: ReplyFlagsView, key: FlagKey): boolean {
  return key === "broken" ? flags.broken !== null : flags[key];
}
