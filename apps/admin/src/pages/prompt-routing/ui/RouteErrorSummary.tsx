import { Button } from "@ai-character-chat/ui/components/button";

import type { AdminPromptRouteCell } from "@/entities/prompt-routing";

import { cellName } from "../model/describe";
import { routeRuleLabel, type RouteRuleItem } from "../model/routeErrors";
import type { RouteCellKey } from "../model/schema";

export type RouteFailureNotice =
  | { kind: "rules"; items: RouteRuleItem[]; restoredNumber: number | null }
  | { kind: "stale"; message: string };

type RouteErrorSummaryProps = {
  notice: RouteFailureNotice;
  cellByKey: ReadonlyMap<RouteCellKey, AdminPromptRouteCell>;
  onFocusCell: (cell: AdminPromptRouteCell) => void;
  onReload: () => void;
  isReloading: boolean;
};

/** 저장·되돌리기 거부를 표 위에 한 번 모아 보인다. 422 는 칸마다의 규칙 위반 목록(항목을 누르면 그 탭·칸으로), 409 는 다른 저장이
 * 먼저 반영됐다는 경고와 최신 표 불러오기다 — 편집을 저절로 버리지 않는다. */
export function RouteErrorSummary({ notice, cellByKey, onFocusCell, onReload, isReloading }: RouteErrorSummaryProps) {
  if (notice.kind === "stale") {
    return (
      <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border border-border p-3">
        <p className="break-keep text-sm text-foreground">{notice.message}</p>
        <Button type="button" variant="outline" size="sm" disabled={isReloading} onClick={onReload}>
          {isReloading ? "불러오는 중..." : "최신 표 불러오기"}
        </Button>
      </div>
    );
  }

  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg bg-destructive/10 p-3">
      <p className="text-sm font-medium text-destructive-text">
        {notice.restoredNumber === null
          ? `저장 검사가 ${notice.items.length}칸을 거부했어요.`
          : `r${notice.restoredNumber} 로 되돌리기를 저장 검사가 거부했어요(${notice.items.length}칸).`}
      </p>
      <ul className="flex flex-col gap-1">
        {notice.items.map((item, index) => {
          const cell = item.key === null ? undefined : cellByKey.get(item.key);
          const prefix = notice.restoredNumber === null ? "" : `r${notice.restoredNumber} 의 이 칸: `;
          const text = `${routeRuleLabel(item.rule)}: ${item.message}`;
          return (
            <li key={`${item.key ?? "unknown"}-${index}`} className="text-sm text-destructive-text">
              {cell === undefined ? (
                <span className="break-keep">지금 표에 없는 칸 — {text}</span>
              ) : (
                <button
                  type="button"
                  className="admin-hit-area rounded-sm text-left underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  onClick={() => onFocusCell(cell)}
                >
                  {prefix}
                  {cellName(cell)} — {text}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
