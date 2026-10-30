import { cn } from "@/shared/lib/cn";

import type { Pane } from "../model/runDetailSearch";

type PaneBarProps = {
  pane: Pane;
  turn: number | undefined;
  turnIndex: number;
  turnCount: number;
  onPaneChange: (pane: Pane) => void;
  onMoveTurn: (step: 1 | -1) => void;
};

const NARROW_PANES = [
  { pane: "turns", label: "턴" },
  { pane: "conversation", label: "대화" },
  { pane: "inspector", label: "호출" },
] as const satisfies ReadonlyArray<{ pane: Pane; label: string }>;

const MEDIUM_PANES = [
  { pane: "conversation", label: "대화·원문" },
  { pane: "inspector", label: "호출" },
] as const satisfies ReadonlyArray<{ pane: Pane; label: string }>;

/**
 * 1280px 미만에서 칸을 바꾸는 줄. 1024~1279px 은 턴 목록이 늘 보여 대화·원문과 호출 검사기를 갈아 끼우고, 1024px 미만은 턴 목록
 * 까지 셋 가운데 하나를 고른다 — 이때는 지금 턴 번호와 앞뒤 턴 버튼도 함께 둔다(턴 목록이 숨어 있어도 턴을 옮길 수 있게).
 */
export function PaneBar({ pane, turn, turnIndex, turnCount, onPaneChange, onMoveTurn }: PaneBarProps) {
  const mediumPane = pane === "inspector" ? "inspector" : "conversation";

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3 xl:hidden">
      <div className="flex items-center gap-1 lg:hidden">
        <StepButton label="이전 턴" isDisabled={turnIndex <= 0} onClick={() => onMoveTurn(-1)}>
          ←
        </StepButton>
        <span className="min-w-16 text-center text-section text-ink tabular-nums">
          턴 {turn ?? "-"}
          <span className="font-normal text-ink-muted">/{turnCount}</span>
        </span>
        <StepButton label="다음 턴" isDisabled={turnIndex === -1 || turnIndex >= turnCount - 1} onClick={() => onMoveTurn(1)}>
          →
        </StepButton>
      </div>
      <Segmented
        className="ml-auto inline-flex lg:hidden"
        options={NARROW_PANES}
        value={pane}
        onChange={onPaneChange}
        label="보일 칸"
      />
      <Segmented
        className="hidden lg:inline-flex"
        options={MEDIUM_PANES}
        value={mediumPane}
        onChange={onPaneChange}
        label="가운데 칸"
      />
    </div>
  );
}

type SegmentedProps = {
  /** 자리와 보일 폭(`inline-flex`/`hidden` 을 브레이크포인트마다) — 부르는 쪽이 정한다. */
  className: string;
  options: ReadonlyArray<{ pane: Pane; label: string }>;
  value: Pane;
  onChange: (pane: Pane) => void;
  label: string;
};

function Segmented({ className, options, value, onChange, label }: SegmentedProps) {
  return (
    <div role="group" aria-label={label} className={cn("rounded-md border border-border p-0.5", className)}>
      {options.map((option) => (
        <button
          key={option.pane}
          type="button"
          aria-pressed={option.pane === value}
          onClick={() => onChange(option.pane)}
          className={cn(
            "h-6 rounded-sm px-2.5 text-data whitespace-nowrap focus-visible:outline-2 focus-visible:outline-accent motion-safe:transition-colors",
            option.pane === value ? "bg-surface-raised font-medium text-accent" : "text-ink-secondary hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function StepButton({
  label,
  isDisabled,
  onClick,
  children,
}: {
  label: string;
  isDisabled: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={isDisabled}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-md border border-border text-body text-ink-secondary enabled:hover:bg-surface-raised enabled:hover:text-ink disabled:text-ink-muted focus-visible:outline-2 focus-visible:outline-accent"
    >
      {children}
    </button>
  );
}
