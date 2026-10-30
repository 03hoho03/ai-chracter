/** 가운데 아래 원문 탭. */
export const RAW_TABS = ["prompt", "instruction", "compare"] as const;
export type RawTab = (typeof RAW_TABS)[number];

/** 오른쪽 검사기 탭 — 단축키 `1`~`4` 가 이 순서다. */
export const INSPECTOR_TABS = ["calls", "memory", "routing", "metrics"] as const;
export type InspectorTab = (typeof INSPECTOR_TABS)[number];

/**
 * 좁은 화면에서 지금 보이는 칸. 1024px 미만은 셋 중 하나만, 1024~1279px 은 턴 목록이 늘 보여 `conversation`·`inspector` 둘을
 * 오가고(그 폭에서 `turns` 는 `conversation` 과 같다), 1280px 이상은 셋을 다 펴서 이 값을 보지 않는다.
 */
export const PANES = ["turns", "conversation", "inspector"] as const;
export type Pane = (typeof PANES)[number];

/** 원문 칸이 보이는 덤프 줄의 종류. `generation` 은 보고 있는 시도에 붙은 생성 덤프이고 나머지는 그 턴의 n번째 줄이다. */
const DUMP_KINDS = ["earlier", "judgment", "background"] as const;
type IndexedDumpKind = (typeof DUMP_KINDS)[number];

export type DumpSource = { kind: "generation" } | { kind: IndexedDumpKind; index: number };

/**
 * 런 상세 주소의 검색 칸. 주소를 붙여 넣거나 새로 고치거나 뒤로 가도 같은 자리가 열리게 고른 것을 다 싣는다.
 * 값이 이 런·이 턴에 실제로 있는지는 데이터를 받은 뒤 `resolve*` 가 본다.
 */
export type RunDetailSearch = {
  /** 고른 턴(드라이버 `clientTurn`, 보충 줄은 서버가 대신 매긴 번호). */
  turn?: number;
  /** 보고 있는 시도(턴 안에서 1부터). 없으면 DB 응답으로 고른 시도. */
  attempt?: number;
  raw?: RawTab;
  inspector?: InspectorTab;
  pane?: Pane;
  /** 원문 칸이 보이는 덤프 줄(`generation`, `judgment-2` 등). */
  dump?: string;
};

const DUMP_PATTERN = /^(earlier|judgment|background)-([1-9]\d*)$/;

/** 라우터가 넘기는 검색 칸을 좁힌다. 라우터는 값을 JSON 으로 먼저 읽어 보므로 숫자가 글로도 수로도 올 수 있다. 모양이 다르면 버린다. */
export function parseRunDetailSearch(search: Record<string, unknown>): RunDetailSearch {
  const parsed: RunDetailSearch = {};
  const turn = asPositiveInteger(search.turn);
  const attempt = asPositiveInteger(search.attempt);
  const raw = asMember(RAW_TABS, search.raw);
  const inspector = asMember(INSPECTOR_TABS, search.inspector);
  const pane = asMember(PANES, search.pane);
  const dump = typeof search.dump === "string" && isDumpText(search.dump) ? search.dump : undefined;
  if (turn !== undefined) parsed.turn = turn;
  if (attempt !== undefined) parsed.attempt = attempt;
  if (raw !== undefined) parsed.raw = raw;
  if (inspector !== undefined) parsed.inspector = inspector;
  if (pane !== undefined) parsed.pane = pane;
  if (dump !== undefined) parsed.dump = dump;
  return parsed;
}

/** 보일 턴 — 주소의 턴이 이 런에 있으면 그 턴, 아니면 첫 턴. 턴이 없는 런이면 undefined. */
export function resolveTurn(turns: ReadonlyArray<{ turn: number }>, requested: number | undefined): number | undefined {
  if (requested !== undefined && turns.some((summary) => summary.turn === requested)) return requested;
  return turns[0]?.turn;
}

/**
 * 보일 시도 — 주소의 시도가 이 턴에 있으면 그 시도, 아니면 DB 응답으로 고른 시도(없으면 첫 시도). 첫 시도가 아니라 고른 시도로
 * 돌아가는 것은, 생성 덤프·턴 기록·지표가 모두 고른 시도에 붙어 있어 그 시도가 이 턴을 대표하기 때문이다.
 */
export function resolveAttempt(
  attempts: ReadonlyArray<{ index: number; selected: boolean }>,
  requested: number | undefined,
): number | undefined {
  if (requested !== undefined && attempts.some((attempt) => attempt.index === requested)) return requested;
  return (attempts.find((attempt) => attempt.selected) ?? attempts[0])?.index;
}

/** 원문 칸이 보일 덤프 줄 — 주소의 줄이 이 턴에 있으면 그것, 아니면 보고 있는 시도의 생성 덤프. */
export function resolveDumpSource(
  requested: string | undefined,
  counts: Readonly<Record<IndexedDumpKind, number>>,
): DumpSource {
  const match = requested === undefined ? null : DUMP_PATTERN.exec(requested);
  const kind = match?.[1];
  const index = Number(match?.[2]);
  if (!isIndexedDumpKind(kind) || index > counts[kind]) return { kind: "generation" };
  return { kind, index };
}

/** 주소에 싣는 원문 출처 글. */
export function dumpSourceText(source: DumpSource): string {
  return source.kind === "generation" ? "generation" : `${source.kind}-${source.index}`;
}

function isDumpText(text: string): boolean {
  return text === "generation" || DUMP_PATTERN.test(text);
}

function isIndexedDumpKind(value: string | undefined): value is IndexedDumpKind {
  return DUMP_KINDS.some((kind) => kind === value);
}

function asPositiveInteger(value: unknown): number | undefined {
  const number = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof number === "number" && Number.isInteger(number) && number > 0 ? number : undefined;
}

function asMember<const Options extends ReadonlyArray<string>>(
  options: Options,
  value: unknown,
): Options[number] | undefined {
  return options.find((option) => option === value);
}
