import type { Caution, Mismatch, ReplyFlagsView, TimelineMarker, TurnMetrics } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";

import { INSPECTOR_TABS, PANES, type InspectorTab, type Pane } from "./runDetailSearch";

/** 불일치 종류의 화면 이름 — 기록끼리 실제로 어긋난 것. */
export const MISMATCH_LABELS = {
  missingDump: "덤프 없는 턴",
  unmatchedRow: "짝 없는 턴 기록 행",
  turnGap: "턴 번호 건너뜀",
  statMismatch: "스탯 대조 어긋남",
  unmatchedDumpLine: "짝 없는 덤프 줄",
  unplacedLine: "자리 없는 줄",
  chatTurnsRoomMismatch: "턴 기록의 방 어긋남",
} as const satisfies Record<Mismatch["kind"], string>;

/** 주의 종류의 화면 이름 — 결합이 어긋났다고 보지 않지만 알아 둘 것. */
export const CAUTION_LABELS = {
  placementEstimated: "배치 추정",
  roomShared: "방 공유",
  incompleteLine: "끝나지 않은 줄",
  unreadableLine: "읽지 못한 줄",
  manifest: "매니페스트",
  notDumpLine: "덤프가 아닌 줄",
  pricesChanged: "가격표 바뀜",
  statDefsChanged: "스탯 정의 바뀜",
  chatTurnsNotJoined: "턴 기록 잇지 않음",
} as const satisfies Record<Caution["kind"], string>;

/** 타임라인 표지 종류 — 측정 서버의 표지와, 턴 요약의 보충 줄 칸에서 오는 "보충 줄". */
export type TimelineMarkKind = TimelineMarker["kind"] | "supplemented";

/**
 * 타임라인 표지의 모양과 낱말. 모양만으로 뜻을 싣지 않도록 낱말을 함께 둔다. 실패만 적색, rebase·재생성·수정은 호박, 나머지는
 * 흐린 글자색이다. `isAfterTurn` 은 드라이버 줄에서 온 표지라 그 턴 뒤(턴 사이)에 놓이는 것. 보충 줄은 사람이 친 턴을 나중에
 * 보충한 줄이라 드라이버가 보낸 턴과 갈라 보이게 한다.
 */
export const MARKER_STYLES = {
  ending: { glyph: "◆", label: "엔딩", tone: "muted", isAfterTurn: false },
  noteChange: { glyph: "●", label: "기억 노트 변경", tone: "muted", isAfterTurn: false },
  summaryUpdate: { glyph: "■", label: "요약 갱신", tone: "muted", isAfterTurn: false },
  rebase: { glyph: "↺", label: "rebase", tone: "warn", isAfterTurn: true },
  regenerate: { glyph: "⟳", label: "재생성", tone: "warn", isAfterTurn: false },
  edit: { glyph: "✎", label: "수정", tone: "warn", isAfterTurn: false },
  check: { glyph: "✓", label: "점검", tone: "muted", isAfterTurn: true },
  noteUpdate: { glyph: "✐", label: "노트 저장", tone: "muted", isAfterTurn: true },
  pause: { glyph: "‖", label: "멈춤", tone: "muted", isAfterTurn: true },
  failure: { glyph: "✕", label: "실패", tone: "danger", isAfterTurn: false },
  supplemented: { glyph: "+", label: "보충 줄", tone: "muted", isAfterTurn: false },
} as const satisfies Record<
  TimelineMarkKind,
  { glyph: string; label: string; tone: "muted" | "warn" | "danger"; isAfterTurn: boolean }
>;

type BooleanFlagKey = Exclude<keyof ReplyFlagsView, "length" | "sentenceCount" | "statusBlockLength" | "broken" | "brackets">;

/** 참/거짓 응답 지표의 화면 이름 — 검사기 지표 탭이 이 순서로 적는다. */
export const BOOLEAN_FLAG_LABELS = {
  truncated: "절단",
  selfCopy: "자기복제",
  labelLeak: "라벨 누출",
  userTurn: "사용자 대사 대필",
  solicit: "질문·청유로 끝남",
  ignored: "발화 무시",
  sceneOpen: "장면 열림",
} as const satisfies Record<BooleanFlagKey, string>;

export const BOOLEAN_FLAG_KEYS = Object.keys(BOOLEAN_FLAG_LABELS).filter(isBooleanFlagKey);

/**
 * 응답 플래그의 화면 이름 — 턴 목록 행(약자의 온 이름)·"먼저 볼 것"·검사기·대화 머리가 모두 여기서 읽는다. 참/거짓 지표는 위 이름
 * 그대로이고, 값 모양이 다른 깨짐(까닭 낱말)·괄호(괄호 목록)를 더한다.
 */
export const REPLY_FLAG_LABELS = {
  ...BOOLEAN_FLAG_LABELS,
  broken: "깨짐",
  brackets: "괄호",
} as const satisfies Record<BooleanFlagKey | "broken" | "brackets", string>;

const INSPECTOR_TAB_LABELS = {
  calls: "호출",
  memory: "기억",
  routing: "라우팅",
  metrics: "지표",
} as const satisfies Record<InspectorTab, string>;

/** 검사기 탭 머리 — 숫자 단축키가 따르는 탭 목록에서 만든다. 탭을 더하거나 옮기면 머리와 단축키가 함께 따라간다. */
export const INSPECTOR_TAB_OPTIONS = INSPECTOR_TABS.map((tab) => ({ tab, label: INSPECTOR_TAB_LABELS[tab] }));

/** 칸 이름 — 1024px 미만에서 셋 가운데 하나를 고르는 줄의 낱말. */
export const PANE_LABELS = {
  turns: "턴",
  conversation: "대화",
  inspector: "호출",
} as const satisfies Record<Pane, string>;

/** 1024px 미만의 칸 고르기 — 칸 목록 전부를 그 순서대로. */
export const NARROW_PANE_OPTIONS = PANES.map((pane) => ({ pane, label: PANE_LABELS[pane] }));

/** 이 턴 지표의 `previous`(자기복제를 견준 직전 응답)가 어디서 왔는지. */
export function describePreviousFrom(metrics: TurnMetrics): string {
  switch (metrics.previousFrom) {
    case "opening":
      return "오프닝 마지막 메시지";
    case "turn":
      return `턴 ${metrics.previousTurn ?? "?"} 응답`;
    case "replacement":
      return `턴 ${metrics.previousTurn ?? "?"} 교체 뒤 응답`;
    case "none":
      return "없음";
    default:
      return assertNever(metrics.previousFrom);
  }
}

function isBooleanFlagKey(key: string): key is BooleanFlagKey {
  return Object.hasOwn(BOOLEAN_FLAG_LABELS, key);
}
