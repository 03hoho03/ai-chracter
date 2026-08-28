import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";

import {
  APPEAL_STATUS_LABELS,
  APPEAL_TARGET_KIND_LABELS,
  useAppealListQuery,
  type AppealStatusFilter,
} from "../../../entities/appeal";
import { AppealResolvePanel } from "../../../features/resolve-appeal";

const STATUS_FILTER_OPTIONS: { value: "all" | AppealStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "pending", label: APPEAL_STATUS_LABELS.pending },
  { value: "resolved", label: APPEAL_STATUS_LABELS.resolved },
];

const dateTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

interface AppealsListPageProps {
  page: number;
  status?: AppealStatusFilter;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: AppealStatusFilter) => void;
}

export function AppealsListPage({ page, status, onPageChange, onStatusChange }: AppealsListPageProps) {
  const appealListQuery = useAppealListQuery({ page, status });
  const [selectedAppealId, setSelectedAppealId] = useState<string>();
  const selectedAppeal = appealListQuery.data?.items.find((item) => item.id === selectedAppealId);

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">이의제기 검토</h1>

        <Select
          value={status ?? "all"}
          onValueChange={(value) => onStatusChange(value === "all" ? undefined : (value as AppealStatusFilter))}
        >
          <SelectTrigger size="sm" aria-label="처리상태 필터" className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTER_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {appealListQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {appealListQuery.isError && (
        <p className="text-sm text-destructive-text">이의제기 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {appealListQuery.data && appealListQuery.data.items.length === 0 && (
        <p className="text-sm text-muted-foreground">접수된 이의제기가 없어요.</p>
      )}

      {appealListQuery.data && appealListQuery.data.items.length > 0 && (
        <>
          <div className="overflow-hidden rounded-xl border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>대상 종류</TableHead>
                  <TableHead>접수일시</TableHead>
                  <TableHead>처리상태</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {appealListQuery.data.items.map((item) => (
                  <TableRow
                    key={item.id}
                    tabIndex={0}
                    role="button"
                    aria-selected={item.id === selectedAppealId}
                    className="cursor-pointer aria-selected:bg-muted"
                    onClick={() => setSelectedAppealId(item.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedAppealId(item.id);
                      }
                    }}
                  >
                    <TableCell>{APPEAL_TARGET_KIND_LABELS[item.targetKind]}</TableCell>
                    <TableCell>{dateTimeFormatter.format(new Date(item.createdAt))}</TableCell>
                    <TableCell>{APPEAL_STATUS_LABELS[item.status]}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              이전
            </Button>
            <span className="text-sm text-muted-foreground">
              {appealListQuery.data.page} / {appealListQuery.data.totalPages} 페이지 (총{" "}
              {appealListQuery.data.totalCount}건)
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page >= appealListQuery.data.totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              다음
            </Button>
          </div>
        </>
      )}

      {selectedAppeal && (
        <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
              {APPEAL_STATUS_LABELS[selectedAppeal.status]}
            </span>
            <span className="text-sm text-muted-foreground">
              {dateTimeFormatter.format(new Date(selectedAppeal.createdAt))} 접수
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-medium text-foreground">신청 사유</h2>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">{selectedAppeal.reasonText}</p>
          </div>

          <AppealResolvePanel appeal={selectedAppeal} />
        </section>
      )}
    </main>
  );
}
