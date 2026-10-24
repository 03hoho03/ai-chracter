import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check } from "lucide-react";
import { useState } from "react";

import {
  PROMPT_MODEL_LABELS,
  ROOM_MODEL_LABELS,
  ROUTE_BACKEND_LABELS,
  ROUTING_LANE_LABELS,
  ROUTING_STAGE_LABELS,
  type AdminPromptRouteRow,
  type AdminPromptRoutingResponse,
} from "@/entities/prompt-routing";
import { useSessionQuery } from "@/entities/session";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DenseTable } from "@/shared/ui/DenseTable";
import { QueryState } from "@/shared/ui/QueryState";

import { useRevisionDetailQuery } from "../api/useRevisionDetailQuery";
import { useRevisionListQuery, type AdminPromptRouteRevisionSummary } from "../api/useRevisionListQuery";
import type { RoutingOutcome } from "../model/outcome";
import { NEUTRAL_BADGE_CLASS, PROBLEM_BADGE_CLASS } from "./badgeClasses";
import { RestoreRoutingDialog } from "./RestoreRoutingDialog";

type RoutingRevisionSectionProps = {
  data: AdminPromptRoutingResponse;
  dirtyCount: number;
  onRestoreOutcome: (outcome: RoutingOutcome, revision: AdminPromptRouteRevisionSummary) => void;
};

/** 프롬프트 화면의 게시 이력과 같은 꼴: 고른 행 아래 그 이력의 행 목록과 되돌리기. */
export function RoutingRevisionSection({ data, dirtyCount, onRestoreOutcome }: RoutingRevisionSectionProps) {
  const revisionListQuery = useRevisionListQuery();

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <h2 className="text-lg font-semibold text-foreground">저장 이력</h2>
      <QueryState
        query={revisionListQuery}
        surface="card"
        errorMessage="저장 이력을 불러오지 못했어요."
        isEmpty={(list) => list.items.length === 0}
        empty={{ title: "아직 저장한 적이 없어요. 표를 처음 저장하면 여기 이력이 쌓이고, 고른 이력으로 되돌릴 수 있어요." }}
      >
        {(list) => (
          <RevisionTable
            items={list.items}
            data={data}
            dirtyCount={dirtyCount}
            onRestoreOutcome={onRestoreOutcome}
          />
        )}
      </QueryState>
    </section>
  );
}

type RevisionTableProps = RoutingRevisionSectionProps & {
  items: AdminPromptRouteRevisionSummary[];
};

function RevisionTable({ items, data, dirtyCount, onRestoreOutcome }: RevisionTableProps) {
  const [selectedId, setSelectedId] = useState<string>();
  const me = useSessionQuery().data;
  const numberById = new Map(items.map((item) => [item.id, item.number]));
  const selected = items.find((item) => item.id === selectedId);

  const restore = async (revision: AdminPromptRouteRevisionSummary) => {
    const outcome = await RestoreRoutingDialog.call({ revision, data, dirtyCount });
    if (outcome === undefined) return;
    if (outcome.status === "saved" && outcome.data.revisionId !== null) setSelectedId(outcome.data.revisionId);
    onRestoreOutcome(outcome, revision);
  };

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-border">
        <DenseTable surface="card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>
                  {/* 값 칸의 체크 글리프 자리만큼 비워 `번호`와 `rN`의 왼쪽 끝을 맞춘다. */}
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden className="size-4" />
                    번호
                  </span>
                </TableHead>
                <TableHead>저장 시각</TableHead>
                <TableHead>칸 수</TableHead>
                <TableHead>메모</TableHead>
                <TableHead>되돌림 출처</TableHead>
                <TableHead>저장한 관리자</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item, index) => {
                const isSelected = item.id === selectedId;
                const restoredFrom =
                  item.restoredFromId === null ? "-" : `r${numberById.get(item.restoredFromId) ?? "?"} 에서`;
                return (
                  // 고른 행은 채움(`DenseTable`)에 더해 체크 글리프로 알린다 — 채움만으로는 card 위 3:1 이 안 나온다. 진입점은 첫
                  // 칸의 네이티브 버튼이고, 그 click 이 `tr` 의 onClick 으로 한 번만 올라간다.
                  <TableRow
                    key={item.id}
                    data-state={isSelected ? "selected" : undefined}
                    className="cursor-pointer"
                    onClick={() => setSelectedId(item.id)}
                  >
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <button
                          type="button"
                          aria-current={isSelected || undefined}
                          className="admin-hit-area flex items-center gap-1.5 rounded-sm text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                        >
                          <Check aria-hidden className={cn("size-4 text-foreground", !isSelected && "invisible")} />r
                          {item.number}
                        </button>
                        {index === 0 && <span className={NEUTRAL_BADGE_CLASS}>지금 표</span>}
                      </span>
                    </TableCell>
                    <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                    <TableCell className="tabular-nums">
                      {item.rowCount === 0 ? "0 (전부 env)" : item.rowCount}
                    </TableCell>
                    <TableCell className="max-w-64 truncate">{item.note || "-"}</TableCell>
                    <TableCell>{restoredFrom}</TableCell>
                    <TableCell>{item.adminId === me?.id ? "나" : item.adminId.slice(0, 8)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </DenseTable>
      </div>

      {selected !== undefined && (
        <RevisionDetailPanel
          revision={selected}
          isLatest={selected.id === items[0]?.id}
          onRestore={() => void restore(selected)}
        />
      )}
    </>
  );
}

type RevisionDetailPanelProps = {
  revision: AdminPromptRouteRevisionSummary;
  isLatest: boolean;
  onRestore: () => void;
};

function RevisionDetailPanel({ revision, isLatest, onRestore }: RevisionDetailPanelProps) {
  const detailQuery = useRevisionDetailQuery(revision.id);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <h3 className="text-sm font-semibold text-foreground">r{revision.number} 의 표</h3>
      <QueryState query={detailQuery} surface="card" errorMessage="이력 상세를 불러오지 못했어요.">
        {(detail) => (
          <div className="flex flex-col gap-2">
            {detail.rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">행이 없어요 — 모든 칸이 env 기본값을 따르는 표예요.</p>
            ) : (
              <ul className="flex flex-col gap-1 text-sm text-foreground">
                {detail.rows.map((row) => (
                  <li key={`${row.lane}|${row.roomModel}|${row.stage}`} className="break-keep">
                    {describeRow(row)}
                  </li>
                ))}
              </ul>
            )}
            {detail.droppedRowCount > 0 && (
              <p className="flex flex-wrap items-center gap-1.5 text-sm text-destructive-text">
                <span className={PROBLEM_BADGE_CLASS}>보이지 않는 행 {detail.droppedRowCount}개</span>
                지금 코드가 모르는 값이 든 행이라 보이지 않아요. 이 이력으로 되돌리면 저장 검사가 거부해요.
              </p>
            )}
          </div>
        )}
      </QueryState>
      <div className="flex flex-wrap items-center gap-2">
        {/* 지금 표인 이력은 되돌릴 것이 없다 — 사유가 읽히도록 `disabled` 대신 `aria-disabled` 로 포커스 순회에 남긴다. */}
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-disabled={isLatest}
          aria-describedby={isLatest ? `routing-revision-${revision.id}-latest` : undefined}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (!isLatest) onRestore();
          }}
        >
          이 이력으로 되돌리기
        </Button>
        {isLatest && (
          <span id={`routing-revision-${revision.id}-latest`} className="text-xs text-muted-foreground">
            지금 표예요
          </span>
        )}
      </div>
    </div>
  );
}

function describeRow(row: AdminPromptRouteRow): string {
  const cell = `${ROUTING_LANE_LABELS[row.lane]} · ${ROOM_MODEL_LABELS[row.roomModel]} · ${ROUTING_STAGE_LABELS[row.stage]}`;
  const route = `${PROMPT_MODEL_LABELS[row.callModel]}·${ROUTE_BACKEND_LABELS[row.backend]}`;
  if (row.chainModel === null) return `${cell} → 방 모델 체인, 경로만 ${ROUTE_BACKEND_LABELS[row.backend]}`;
  return `${cell} → ${PROMPT_MODEL_LABELS[row.chainModel]} 체인, ${route}`;
}
