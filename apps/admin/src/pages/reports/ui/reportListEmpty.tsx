import { Button } from "@ai-character-chat/ui/components/button";

import type { ReportStatusFilter } from "@/entities/report";

/** 신고 표 셋이 같은 빈 상태를 쓴다 — 처리상태를 걸었으면 그 필터를 푸는 길을, 아니면 무엇이 여기 쌓이는지를 알린다. */
export function reportListEmpty({ noun, status, onReset }: { noun: string; status?: ReportStatusFilter; onReset: () => void }) {
  if (status === undefined) return { title: `접수된 ${noun}가 없어요. 새로 들어오면 여기에 쌓여요.` };
  return {
    title: `이 상태의 ${noun}가 없어요.`,
    action: (
      <Button type="button" variant="outline" size="sm" onClick={onReset}>
        필터 초기화
      </Button>
    ),
  };
}
