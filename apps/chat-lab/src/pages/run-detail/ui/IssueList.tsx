import type { Caution, Mismatch } from "@/shared/api/client";
import { formatCount } from "@/shared/lib/formatNumber";
import { Button } from "@/shared/ui/Button";

import { CAUTION_LABELS, MISMATCH_LABELS } from "../model/detailLabels";

type IssueListProps = {
  mismatches: ReadonlyArray<Mismatch>;
  cautions: ReadonlyArray<Caution>;
  /** 이 런에 있는 턴 번호. 목록 항목이 가리키는 턴이 여기 없으면(건너뛴 번호·짝 없는 줄의 번호) 고를 수 없다. */
  knownTurns: ReadonlySet<number>;
  onSelectTurn: (turn: number) => void;
  onClose: () => void;
};

/**
 * 상태 줄에서 펼치는 불일치·주의 목록 — 종류 · 턴 · 설명. 둘은 따로 센다(주의를 불일치 수에 더하지 않는다). 턴을 누르면 그 턴으로
 * 가고 목록은 열어 둔다(여러 턴을 차례로 훑기). 이 런에 없는 턴 번호는 누를 수 없는 글자로 적는다 — 누르면 엉뚱한 턴(첫 턴)이
 * 열린다. 잠깐 떠서 본문을 가리는 층이라 그림자가 있다.
 */
export function IssueList({ mismatches, cautions, knownTurns, onSelectTurn, onClose }: IssueListProps) {
  return (
    <section
      id="run-issues"
      aria-label="불일치·주의 목록"
      className="absolute inset-x-0 bottom-0 z-30 flex max-h-[45%] flex-col bg-surface shadow-overlay"
    >
      <div className="flex h-8 shrink-0 items-center gap-3 border-b border-border px-3">
        <h2 className="text-section text-ink">
          불일치 <span className="text-warn tabular-nums">{formatCount(mismatches.length)}</span>
          <span className="text-ink-muted"> · </span>
          주의 <span className="text-warn tabular-nums">{formatCount(cautions.length)}</span>
        </h2>
        <span className="ml-auto" />
        <Button onClick={onClose} aria-label="불일치·주의 목록 닫기">
          닫기 <span className="text-label text-ink-muted">Esc</span>
        </Button>
      </div>
      {/* `relative` 는 항목 안의 읽기 프로그램 전용 낱말(절대 위치)이 이 스크롤 안에 붙게 한다 — 없으면 스크롤 밖의 패널에 붙어,
          아래쪽 항목의 그 낱말이 화면 전체를 세로로 늘린다. 항목 행이 아니라 여기에 두는 것은, 행을 위치 요소로 만들면 스크롤된
          행이 고정된 묶음 머리 위로 그려지기 때문이다. */}
      <div className="relative min-h-0 overflow-auto">
        <IssueSection
          title="불일치"
          note="기록끼리 실제로 어긋난 것"
          items={mismatches.map((mismatch) => ({ ...mismatch, label: MISMATCH_LABELS[mismatch.kind] }))}
          knownTurns={knownTurns}
          onSelectTurn={onSelectTurn}
        />
        <IssueSection
          title="주의"
          note="결합이 어긋났다고 보지 않지만 알아 둘 것"
          items={cautions.map((caution) => ({ ...caution, label: CAUTION_LABELS[caution.kind] }))}
          knownTurns={knownTurns}
          onSelectTurn={onSelectTurn}
        />
      </div>
    </section>
  );
}

type IssueItem = {
  label: string;
  turn?: number | null;
  detail: string;
};

type IssueSectionProps = {
  title: string;
  note: string;
  items: ReadonlyArray<IssueItem>;
  knownTurns: ReadonlySet<number>;
  onSelectTurn: (turn: number) => void;
};

function IssueSection({ title, note, items, knownTurns, onSelectTurn }: IssueSectionProps) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="sticky top-0 bg-surface px-3 pt-2 pb-1 text-label font-semibold text-ink-secondary">
        {title} <span className="font-normal text-ink-muted">· {note}</span>
      </h3>
      <ul className="text-data">
        {items.map(({ label, turn, detail }, index) => (
          // 서버가 준 순서 그대로이고 바뀌지 않는다.
          <li
            key={index}
            className="grid grid-cols-[minmax(0,1fr)_4rem] items-baseline gap-2 border-b border-border px-3 py-1.5 sm:grid-cols-[7rem_4rem_minmax(0,1fr)]"
          >
            <span className="truncate text-warn">{label}</span>
            <span className="tabular-nums">
              <IssueTurn turn={turn} knownTurns={knownTurns} onSelectTurn={onSelectTurn} />
            </span>
            <span className="col-span-2 text-ink-secondary wrap-anywhere sm:col-span-1">{detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type IssueTurnProps = {
  turn: number | null | undefined;
  knownTurns: ReadonlySet<number>;
  onSelectTurn: (turn: number) => void;
};

/** 항목의 턴 칸 — 이 런에 있는 턴이면 그 턴으로 가는 버튼, 없는 번호면 글자, 턴을 가리키지 않으면 "턴 없음". */
function IssueTurn({ turn, knownTurns, onSelectTurn }: IssueTurnProps) {
  if (typeof turn !== "number") return <span className="text-ink-muted">턴 없음</span>;
  if (!knownTurns.has(turn)) {
    // 턴 칸이 좁아(4rem) 번호 아래 줄에 적는다.
    return (
      <span className="text-ink-muted">
        턴 {turn}
        <span className="block text-label">
          <span className="sr-only">· </span>런에 없음
        </span>
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onSelectTurn(turn)}
      className="rounded-sm text-ink underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
    >
      턴 {turn}
    </button>
  );
}
