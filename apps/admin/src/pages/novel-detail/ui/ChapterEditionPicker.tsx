import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { useId } from "react";

import type { AdminNovelChapterEditionItem } from "@/entities/admin-novel";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

type ChapterEditionPickerProps = {
  editions: readonly AdminNovelChapterEditionItem[];
  value: number;
  onValueChange: (edition: number) => void;
};

/**
 * 화 펼침 머리의 판 고르기. 항목은 판 번호·공개 시각(지금 판 표시)이고, 고른 판의 변경 요약은 고르기 아래 한 줄로 둔다 — 요약은
 * 100자까지라 목록 항목에 넣으면 한 줄 트리거에서 잘린다. 같은 날 두 번 공개할 수 있어 날짜만이 아니라 시각까지 적는다.
 */
export function ChapterEditionPicker({ editions, value, onValueChange }: ChapterEditionPickerProps) {
  const id = useId();
  const labelId = `${id}-label`;
  const summaryId = `${id}-summary`;
  const picked = editions.find((item) => item.edition === value);
  const summary = picked?.changeSummary;

  return (
    <div className="flex flex-col gap-1.5">
      <Label id={labelId}>판</Label>
      <Select
        value={String(value)}
        onValueChange={(raw) => {
          const next = editions.find((item) => String(item.edition) === raw);
          if (next) onValueChange(next.edition);
        }}
      >
        <SelectTrigger
          className="w-full max-w-sm"
          aria-labelledby={labelId}
          aria-describedby={summary ? summaryId : undefined}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {editions.map((item) => (
            <SelectItem key={item.edition} value={String(item.edition)}>
              {editionLabel(item)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {!!summary && (
        <p id={summaryId} className="break-keep text-xs text-muted-foreground wrap-anywhere">
          변경 요약: {summary}
        </p>
      )}
    </div>
  );
}

function editionLabel(item: AdminNovelChapterEditionItem): string {
  const label = `${item.edition}판 · ${formatDateTime(item.publishedAt)}`;
  return item.current ? `${label} (지금 판)` : label;
}
