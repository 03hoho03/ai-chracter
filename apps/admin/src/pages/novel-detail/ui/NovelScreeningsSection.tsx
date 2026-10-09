import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";

import {
  NOVEL_FLAGGED_PART_LABELS,
  NOVEL_SCREENING_OUTCOME_LABELS,
  type AdminNovelDetailResponse,
} from "@/entities/admin-novel";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

type NovelScreening = AdminNovelDetailResponse["screenings"][number];

/** 공개할 때마다 돈 텍스트 심사 기록. 사유는 심사 모델이 쓴 글이라 운영자만 본다(게시자에게는 걸린 자리만 간다). */
export function NovelScreeningsSection({ screenings }: { screenings: NovelScreening[] }) {
  return (
    <section
      aria-labelledby="novel-screenings-heading"
      className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6"
    >
      <h2 id="novel-screenings-heading" className="text-lg font-semibold text-foreground">
        심사 기록
      </h2>
      {screenings.length === 0 ? (
        <p className="text-sm text-muted-foreground">심사 기록이 없어요.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>일시</TableHead>
                <TableHead>대상</TableHead>
                <TableHead>결과</TableHead>
                <TableHead>걸린 자리</TableHead>
                <TableHead>사유</TableHead>
                <TableHead>모델</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {screenings.map((screening) => (
                <TableRow key={`${screening.createdAt}-${screening.chapterOrdinal ?? "novel"}-${screening.outcome}`}>
                  <TableCell>{formatDateTime(screening.createdAt)}</TableCell>
                  <TableCell>{screening.chapterOrdinal === null ? "제목·소개" : `${screening.chapterOrdinal}화`}</TableCell>
                  <TableCell className={screening.outcome === "rejected" ? "font-medium text-destructive-text" : undefined}>
                    {NOVEL_SCREENING_OUTCOME_LABELS[screening.outcome]}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {screening.flaggedParts.length === 0
                      ? "-"
                      : screening.flaggedParts.map((part) => NOVEL_FLAGGED_PART_LABELS[part]).join(", ")}
                  </TableCell>
                  {/* 모델이 쓴 사유라 길 수 있다 — 이 칸만 줄바꿈해 다른 칸이 표 밖으로 밀리지 않게 한다. */}
                  <TableCell className="min-w-56 whitespace-normal break-keep wrap-anywhere">{screening.reason ?? "-"}</TableCell>
                  <TableCell className="text-muted-foreground">{screening.model}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
