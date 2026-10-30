import type { Caution, Mismatch, ReplyFlagsView, TimelineMarker, TurnMetrics } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";

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
} as const satisfies Record<Caution["kind"], string>;

/**
 * 타임라인 표지의 모양과 낱말. 모양만으로 뜻을 싣지 않도록 낱말을 함께 둔다. 실패만 적색, rebase·재생성·수정은 호박, 나머지는
 * 흐린 글자색이다. `isAfterTurn` 은 드라이버 줄에서 온 표지라 그 턴 뒤(턴 사이)에 놓이는 것.
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
} as const satisfies Record<
  TimelineMarker["kind"],
  { glyph: string; label: string; tone: "muted" | "warn" | "danger"; isAfterTurn: boolean }
>;

type BooleanFlagKey = Exclude<keyof ReplyFlagsView, "length" | "sentenceCount" | "broken" | "brackets">;

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
