import { useNavigate } from "@tanstack/react-router";
import { useCallback, useMemo, useRef, useState } from "react";

import type { RunListItem } from "@/shared/api/client";
import { Button } from "@/shared/ui/Button";

import { useRowKeys } from "../lib/useRowKeys";
import { ancestorFolders, buildFolderTree, isFolderExpanded, type FolderNode } from "../model/folderTree";
import { formatCount } from "../model/runFormat";
import { rowsInFolder, type RunRow } from "../model/runRows";
import { FolderTree } from "./FolderTree";
import { RunPreview } from "./RunPreview";
import { RunTable } from "./RunTable";

type RunWorkbenchProps = {
  items: ReadonlyArray<RunListItem>;
  folder: string;
  selectedRowKey: string | undefined;
};

/**
 * 3열 작업대 — 폴더 트리 │ 런 표 │ 미리보기. 좁아지면 미리보기(1280 미만), 폴더 트리(1024 미만) 순으로 접고 표는 남는다.
 * 고른 폴더와 행은 주소에 있어(`?folder=…&row=…`) 런 상세에서 돌아오면 보던 자리다.
 */
export function RunWorkbench({ items, folder, selectedRowKey }: RunWorkbenchProps) {
  const navigate = useNavigate({ from: "/" });
  const tree = useMemo(() => buildFolderTree(items), [items]);
  const rows = useMemo(() => rowsInFolder(items, folder), [items, folder]);
  // 손으로 펼치거나 접은 폴더만 적는다. 나머지는 기본값을 따른다(`isFolderExpanded`).
  const [expandOverrides, setExpandOverrides] = useState<ReadonlyMap<string, boolean>>(() => new Map());
  const tableRef = useRef<HTMLDivElement>(null);

  const selectedIndex = rows.findIndex((row) => row.key === selectedRowKey);
  const activeIndex = selectedIndex === -1 ? 0 : selectedIndex;
  const activeRow = rows[activeIndex];
  const runCount = rows.reduce((count, row) => count + (row.kind === "run" ? 1 : row.summary.runCount), 0);

  function isExpanded(node: FolderNode): boolean {
    return isFolderExpanded(node, expandOverrides);
  }

  function handleToggleFolder(node: FolderNode) {
    setExpandOverrides((previous) => new Map(previous).set(node.path, !isFolderExpanded(node, previous)));
  }

  // 표의 행에 넘기는 두 콜백은 렌더마다 새로 만들지 않는다 — 행이 메모되어 있어, 바뀌면 천 행이 다시 그려진다.
  const selectFolder = useCallback(
    (path: string) => {
      // 표의 그룹 행으로 들어가면 트리에서도 그 폴더가 보이도록 조상 폴더를 편다.
      setExpandOverrides((previous) => {
        const next = new Map(previous);
        for (const ancestor of ancestorFolders(path)) next.set(ancestor, true);
        return next;
      });
      void navigate({ search: path === "" ? {} : { folder: path } });
    },
    [navigate],
  );

  const selectRow = useCallback(
    (key: string) => {
      void navigate({ search: (previous) => ({ ...previous, row: key }), replace: true });
    },
    [navigate],
  );

  const openRow = useCallback(
    (row: RunRow) => {
      if (row.kind === "group") {
        selectFolder(row.folder);
        return;
      }
      void navigate({ to: "/runs/$runId", params: { runId: row.item.runId } });
    },
    [navigate, selectFolder],
  );

  function handleMove(step: 1 | -1) {
    const next = rows[Math.min(rows.length - 1, Math.max(0, activeIndex + step))];
    if (!next) return;
    // 포커스를 새 행으로 옮기면 그 행이 포커스를 받으며 스스로 골라진다. 행을 찾지 못했을 때만 직접 고른다.
    if (!revealRow(tableRef.current, next.key)) selectRow(next.key);
  }

  function handleOpenActive() {
    if (activeRow) openRow(activeRow);
  }

  useRowKeys({ onMove: handleMove, onOpen: handleOpenActive });

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_20rem]">
      <section aria-label="폴더" className="hidden min-h-0 overflow-auto border-r border-border bg-surface lg:block">
        <div className="sticky top-0 z-10 flex h-8 items-center border-b border-border bg-surface px-3">
          <h2 className="text-section text-ink">폴더</h2>
        </div>
        <FolderTree
          root={tree}
          selectedFolder={folder}
          isExpanded={isExpanded}
          onToggle={handleToggleFolder}
          onSelect={selectFolder}
        />
      </section>
      <section aria-label="런 표" className="min-h-0 overflow-auto bg-surface">
        <div className="sticky top-0 z-20 flex h-8 items-center gap-2 border-b border-border bg-surface px-3">
          <h2 className={folder === "" ? "truncate text-section text-ink" : "truncate font-mono text-section text-ink"}>
            {folder === "" ? "전체" : folder}
          </h2>
          <span className="shrink-0 text-data text-ink-muted tabular-nums">런 {formatCount(runCount)}</span>
        </div>
        {rows.length === 0 ? (
          <div className="space-y-3 px-3 py-6 text-body text-ink-secondary">
            <p>이 폴더 아래에는 런이 없다. 주소의 폴더가 옛 것이거나, 새로 훑은 뒤 폴더가 사라졌다.</p>
            <Button onClick={() => selectFolder("")}>전체 보기</Button>
          </div>
        ) : (
          <RunTable
            rows={rows}
            folder={folder}
            activeKey={activeRow?.key}
            tableRef={tableRef}
            onSelectRow={selectRow}
            onOpenRow={openRow}
          />
        )}
      </section>
      <aside aria-label="미리보기" className="hidden min-h-0 overflow-auto border-l border-border bg-surface xl:block">
        <RunPreview row={activeRow} folder={folder} onOpen={openRow} />
      </aside>
    </div>
  );
}

/**
 * 행을 표 스크롤 안에 들이고 그 행의 링크로 포커스를 옮긴다. 포커스가 트리·빵부스러기·토글에 남아 있으면 이어서 누른 Enter 가
 * 그 버튼을 누르기 때문에, j/k 뒤에는 늘 고른 행이 Enter 를 받게 한다. 화면 읽기 프로그램도 새 행을 따라온다. 행은 이미 그려져
 * 있고 강조만 바뀌므로 상태 갱신을 기다리지 않아도 된다. 포커스를 옮겼으면 참.
 */
function revealRow(table: HTMLDivElement | null, key: string): boolean {
  const row = table?.querySelector<HTMLElement>(`[data-row-key="${CSS.escape(key)}"]`);
  const target = row?.querySelector<HTMLElement>("[data-row-focus]");
  if (!row || !target) return false;
  row.scrollIntoView({ block: "nearest" });
  target.focus({ preventScroll: true });
  return true;
}
