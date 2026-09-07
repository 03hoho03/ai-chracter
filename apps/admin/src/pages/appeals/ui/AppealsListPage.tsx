import { useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";

import {
  APPEAL_STATUS_LABELS,
  APPEAL_TARGET_KIND_LABELS,
  useAppealListQuery,
  type AppealStatusFilter,
} from "@/entities/appeal";
import { AppealResolvePanel } from "@/features/resolve-appeal";
import { Pagination } from "@/shared/ui/Pagination";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

const STATUS_FILTER_OPTIONS: { value: "all" | AppealStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "pending", label: APPEAL_STATUS_LABELS.pending },
  { value: "resolved", label: APPEAL_STATUS_LABELS.resolved },
];

type AppealsListPageProps = {
  page: number;
  status?: AppealStatusFilter;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: AppealStatusFilter) => void;
}

export function AppealsListPage({ page, status, onPageChange, onStatusChange }: AppealsListPageProps) {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">이의제기 검토</h1>

        <Select
          value={status ?? "all"}
          onValueChange={(value) => onStatusChange(isAppealStatus(value) ? value : undefined)}
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

      <AppealsTable page={page} status={status} onPageChange={onPageChange} />
    </main>
  );
}

type AppealsTableProps = {
  page: number;
  status?: AppealStatusFilter;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. 선택된 항목의
 * 상세도 목록 응답에서 바로 찾으므로(US-124 — 별도 detail API가 없다) 여기 함께 둔다. */
function AppealsTable({ page, status, onPageChange }: AppealsTableProps) {
  const appealListQuery = useAppealListQuery({ page, status });
  const [selectedAppealId, setSelectedAppealId] = useState<string>();

  if (appealListQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (appealListQuery.isError) {
    return <p className="text-sm text-destructive-text">이의제기 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (appealListQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">접수된 이의제기가 없어요.</p>;
  }

  const selectedAppeal = appealListQuery.data.items.find((item) => item.id === selectedAppealId);

  return (
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
                <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                <TableCell>{APPEAL_STATUS_LABELS[item.status]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Pagination
        page={appealListQuery.data.page}
        totalPages={appealListQuery.data.totalPages}
        totalCount={appealListQuery.data.totalCount}
        onPageChange={onPageChange}
      />

      {selectedAppeal && (
        <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
              {APPEAL_STATUS_LABELS[selectedAppeal.status]}
            </span>
            <span className="text-sm text-muted-foreground">
              {formatDateTime(selectedAppeal.createdAt)} 접수
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-medium text-foreground">신청 사유</h2>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">{selectedAppeal.reasonText}</p>
          </div>

          <AppealResolvePanel appeal={selectedAppeal} />
        </section>
      )}
    </>
  );
}

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다(TS-03).
 * 목록에 섞여 있는 `"all"`은 "필터 없음"이라 여기서 자연히 걸러진다 — 술어가 false면 호출부가
 * `undefined`를 넘긴다. */
function isAppealStatus(value: string): value is AppealStatusFilter {
  return STATUS_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}
