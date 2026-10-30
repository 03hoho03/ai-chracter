import { Link } from "@tanstack/react-router";
import { memo, type MouseEvent, type RefObject } from "react";

import type { RunListItem } from "@/shared/api/client";
import { cn } from "@/shared/lib/cn";

import { relativeToFolder } from "../model/folderTree";
import {
  describeGroupCost,
  describeRunCost,
  formatCount,
  formatDateRange,
  formatStartedAt,
  summarizeModels,
} from "../model/runFormat";
import { isOpened, type RunRow } from "../model/runRows";
import { CostText } from "./CostText";

type RunTableProps = {
  rows: ReadonlyArray<RunRow>;
  folder: string;
  activeKey: string | undefined;
  tableRef: RefObject<HTMLDivElement | null>;
  onSelectRow: (key: string) => void;
  onOpenRow: (row: RunRow) => void;
};

/**
 * 칸 배치. 좁은 화면은 이야기·턴·원가·불일치 넷, `md` 부터 경로·시작·모델·주의를 더한다. 머리 줄과 행이 같은 배치를 써야 칸이
 * 맞아서 한 곳에 둔다. 숫자 칸 폭은 가장 긴 값(`≥ $12.3456`, "내보내기 필요")이 12px 고정폭 숫자로 들어가는 폭이다.
 */
const ROW_GRID =
  "grid grid-cols-[minmax(0,1fr)_2.5rem_6.5rem_3.5rem] md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_5.5rem_2.5rem_minmax(0,1fr)_6.5rem_3.5rem_3rem]";

const ROW_BASE = "h-7 scroll-mt-16 items-center border-b border-border text-data";

const CELL = "min-w-0 truncate px-2";
const NUMBER_CELL = "truncate px-2 text-right tabular-nums";
const WIDE_ONLY = "hidden md:block";

/**
 * 가운데 런 표. 행을 한 번 누르면 고르고(미리보기가 따라온다), 두 번 누르거나 고른 행에서 Enter 면 연다 — 런은 상세로, 그룹 행은
 * 그 폴더로 들어간다. 고르기와 열기를 나눈 것은 미리보기로 먼저 훑고 여는 흐름 때문이다.
 */
export function RunTable({ rows, folder, activeKey, tableRef, onSelectRow, onOpenRow }: RunTableProps) {
  return (
    <div role="table" aria-label="런" ref={tableRef}>
      <div role="rowgroup" className="sticky top-8 z-10 bg-surface">
        <div role="row" className={cn(ROW_GRID, "h-7 items-center border-b border-border-strong text-label text-ink-muted")}>
          <span role="columnheader" className={CELL}>
            이야기
          </span>
          <span role="columnheader" className={cn(CELL, WIDE_ONLY)}>
            경로
          </span>
          <span role="columnheader" className={cn(CELL, WIDE_ONLY)}>
            시작
          </span>
          <span role="columnheader" className={NUMBER_CELL}>
            턴
          </span>
          <span role="columnheader" className={cn(CELL, WIDE_ONLY)}>
            모델
          </span>
          <span role="columnheader" className={NUMBER_CELL}>
            원가
          </span>
          <span role="columnheader" className={NUMBER_CELL}>
            불일치
          </span>
          <span role="columnheader" className={cn(NUMBER_CELL, WIDE_ONLY)}>
            주의
          </span>
        </div>
      </div>
      <div role="rowgroup">
        {rows.map((row) =>
          row.kind === "run" ? (
            <RunTableRow
              key={row.key}
              row={row}
              folder={folder}
              isActive={row.key === activeKey}
              onSelect={onSelectRow}
              onOpen={onOpenRow}
            />
          ) : (
            <GroupTableRow
              key={row.key}
              row={row}
              folder={folder}
              isActive={row.key === activeKey}
              onSelect={onSelectRow}
              onOpen={onOpenRow}
            />
          ),
        )}
      </div>
    </div>
  );
}

type RowProps<Kind extends RunRow["kind"]> = {
  row: Extract<RunRow, { kind: Kind }>;
  folder: string;
  isActive: boolean;
  onSelect: (key: string) => void;
  onOpen: (row: RunRow) => void;
};

// 행은 메모한다 — j/k 로 옮길 때 바뀌는 것은 앞뒤 두 행의 `isActive` 뿐인데, 대량 시도 폴더 하나가 천 행을 넘을 수 있다.
const RunTableRow = memo(function RunTableRow({ row, folder, isActive, onSelect, onOpen }: RowProps<"run">) {
  const { item } = row;
  const models = summarizeModels(item);
  const startedAt = formatStartedAt(item.startedAt);

  return (
    <div
      role="row"
      data-row-key={row.key}
      aria-current={isActive ? "true" : undefined}
      onClick={() => onSelect(row.key)}
      onDoubleClick={() => onOpen(row)}
      className={cn(ROW_GRID, ROW_BASE, "cursor-default select-none", rowStateClass(isActive))}
    >
      <span role="cell" className="flex min-w-0 items-center gap-1.5 px-2">
        <Link
          to="/runs/$runId"
          params={{ runId: item.runId }}
          data-row-focus=""
          tabIndex={isActive ? 0 : -1}
          onFocus={isActive ? undefined : () => onSelect(row.key)}
          onClick={(event) => handleRowLinkClick(event, row, onOpen)}
          title={item.path}
          className={cn("min-w-0 truncate outline-none", isActive && "font-semibold", nameToneClass(item))}
        >
          {runName(item)}
        </Link>
        {item.format === "preMessageId" && (
          <span
            title="이전 형식 — 드라이버 턴 줄에 메시지 id 가 없다"
            className="inline-flex h-[18px] shrink-0 items-center rounded-sm border border-border-strong px-1.5 text-label text-ink-secondary"
          >
            이전
          </span>
        )}
      </span>
      {isOpened(item) ? (
        <>
          <span role="cell" title={item.path} className={cn(CELL, WIDE_ONLY, "font-mono text-ink-muted")}>
            {relativeToFolder(item.path, folder)}
          </span>
          <span role="cell" title={item.startedAt ?? undefined} className={cn(CELL, WIDE_ONLY, "tabular-nums")}>
            {startedAt ?? <span className="text-ink-muted">기록 없음</span>}
          </span>
          <span role="cell" className={NUMBER_CELL}>
            {item.turnCount}
          </span>
          <span
            role="cell"
            title={[...(item.effectiveChatModels ?? []), ...(item.generationModels ?? [])].join(", ")}
            className={cn(CELL, WIDE_ONLY)}
          >
            {models ? (
              <>
                <span className="font-mono">{models.first}</span>
                {models.extraCount > 0 && <span className="text-ink-muted"> +{models.extraCount}</span>}
              </>
            ) : (
              <span className="text-ink-muted">기록 없음</span>
            )}
          </span>
          <span role="cell" className={NUMBER_CELL}>
            <CostText cost={describeRunCost(item)} />
          </span>
          <span role="cell" className={NUMBER_CELL}>
            <WarnCount value={item.mismatchCount} />
          </span>
          <span role="cell" className={cn(NUMBER_CELL, WIDE_ONLY)}>
            <WarnCount value={item.cautionCount} />
          </span>
        </>
      ) : (
        <span role="cell" title={item.openError ?? item.path} className="col-[2/-1] min-w-0 truncate px-2">
          <span className="font-mono text-ink-muted">{relativeToFolder(item.path, folder)}</span>
          <span className="text-ink-secondary">
            {" — "}
            {item.openError ?? "옛 형식이라 열지 않는다(드라이버 턴 줄에 방 id 가 없다)"}
          </span>
        </span>
      )}
    </div>
  );
});

const GroupTableRow = memo(function GroupTableRow({ row, folder, isActive, onSelect, onOpen }: RowProps<"group">) {
  const { summary } = row;

  return (
    <div
      role="row"
      data-row-key={row.key}
      aria-current={isActive ? "true" : undefined}
      onClick={() => onSelect(row.key)}
      onDoubleClick={() => onOpen(row)}
      className={cn(ROW_GRID, ROW_BASE, "cursor-default select-none", rowStateClass(isActive))}
    >
      <span role="cell" className="flex min-w-0 items-center gap-1.5 px-2">
        <Link
          to="/"
          search={{ folder: row.folder }}
          data-row-focus=""
          tabIndex={isActive ? 0 : -1}
          onFocus={isActive ? undefined : () => onSelect(row.key)}
          onClick={(event) => handleRowLinkClick(event, row, onOpen)}
          title={`${row.folder} — 들어가면 런마다 행이 놓인다`}
          className="flex min-w-0 items-center gap-1.5 outline-none"
        >
          <span aria-hidden="true" className="text-ink-muted">
            ▸
          </span>
          <span className={cn("truncate font-mono text-ink", isActive && "font-semibold")}>
            {relativeToFolder(row.folder, folder)}
          </span>
        </Link>
        <span className="shrink-0 text-ink-muted">런 {formatCount(summary.runCount)}개</span>
        {summary.unopenedCount > 0 && (
          <span className="shrink-0 text-danger">열 수 없음 {formatCount(summary.unopenedCount)}</span>
        )}
      </span>
      <span role="cell" className={cn(CELL, WIDE_ONLY)} />
      <span role="cell" className={cn(CELL, WIDE_ONLY, "tabular-nums")}>
        {formatDateRange(summary.earliestStartedAt, summary.latestStartedAt)}
      </span>
      <span role="cell" className={NUMBER_CELL} />
      <span role="cell" className={cn(CELL, WIDE_ONLY)} />
      <span role="cell" className={NUMBER_CELL}>
        <CostText cost={describeGroupCost(summary)} />
      </span>
      <span role="cell" className={NUMBER_CELL}>
        <WarnCount value={summary.mismatchTotal} />
      </span>
      <span role="cell" className={cn(NUMBER_CELL, WIDE_ONLY)}>
        <WarnCount value={summary.cautionTotal} />
      </span>
    </div>
  );
});

/**
 * 행 링크를 눌렀을 때. 마우스 한 번은 고르기라 링크 이동을 막고 행에 맡긴다. 키보드 Enter 로 생긴 클릭(`detail` 0)은 열기다.
 * 보조키를 쥔 클릭은 손대지 않아 브라우저가 새 탭·새 창으로 연다 — 링크로 둔 까닭이다.
 */
function handleRowLinkClick(event: MouseEvent<HTMLAnchorElement>, row: RunRow, onOpen: (row: RunRow) => void) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  if (event.detail === 0) {
    event.stopPropagation();
    onOpen(row);
  }
}

/** 불일치·주의 수. 0 이면 아무것도 그리지 않는다 — 정상이 가장 조용해야 이상한 것이 보인다. */
function WarnCount({ value }: { value: number | null | undefined }) {
  if (value == null || value === 0) return null;
  return <span className="text-warn">{formatCount(value)}</span>;
}

/** 고른 행은 올라온 면 + 코발트 1px 윤곽, 키보드로 포커스하면 2px. 옆줄 강조선은 쓰지 않는다. */
function rowStateClass(isActive: boolean): string {
  return cn(
    "motion-safe:transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:-outline-offset-2 has-[:focus-visible]:outline-accent",
    isActive ? "bg-surface-raised outline-1 -outline-offset-1 outline-accent" : "hover:bg-surface-raised",
  );
}

/** 이야기 칸의 이름 — 열지 못한 런은 이름 자리에 그 상태를 적고, 까닭은 나머지 칸 자리에 둔다. */
function runName(item: RunListItem): string {
  if (item.openError != null) return "열 수 없음";
  if (!item.supported) return "지원 안 함";
  return item.storyName ?? "이야기 이름 없음";
}

function nameToneClass(item: RunListItem): string {
  if (!isOpened(item)) return "text-danger";
  return item.storyName == null ? "text-ink-muted" : "text-ink";
}
