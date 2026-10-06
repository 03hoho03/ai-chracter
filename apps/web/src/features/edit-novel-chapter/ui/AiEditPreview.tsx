import { Button } from "@ai-character-chat/ui/components/button";
import { useId } from "react";

import type { NovelPendingAiEdit } from "@/entities/novel";

import { toAiEditComparison } from "../model/chapterBody";
import { clampParagraphRange, formatParagraphRange } from "../model/paragraphRange";

type AiEditPreviewProps = {
  edit: NovelPendingAiEdit;
  /** 지금 본문의 문단. 수정안은 이 본문을 기준으로 만들어졌다(기준이 바뀐 수정안은 서버가 목록에서 뺀다). */
  paragraphs: readonly string[];
  /** 이 수정안이나 다른 수정안을 적용·버리는 중인가. */
  isActing: boolean;
  onApply: () => void;
  onDismiss: () => void;
};

/** 적용하지 않은 AI 수정안 하나. 고른 범위의 마지막 문단 바로 아래에 놓이고, 지금 글과 수정안을 위아래로 둔다
 * (한 줄 폭이 읽기 폭이라 나란히 두면 둘 다 반으로 접힌다).
 *
 * 수정안은 아직 본문이 아니라 무채색 테두리 상자로 본문과 가른다 — 색 채움은 쓰지 않는다(이 화면의 유일한
 * 솔리드 채움은 다음 장 만들기다). 적용은 회색 채움, 버리기는 테두리 버튼이고 순서는 버리기 먼저다(확인
 * 단계의 `취소` 먼저와 같은 자리). 버려도 클로버가 돌아오지 않는다는 문장을 버튼 바로 위에 둔다. */
export function AiEditPreview({ edit, paragraphs, isActing, onApply, onDismiss }: AiEditPreviewProps) {
  const headingId = useId();
  const range = clampParagraphRange({ start: edit.paragraphStart, end: edit.paragraphEnd }, paragraphs.length) ?? {
    start: 0,
    end: 0,
  };
  const { original, candidate } = toAiEditComparison(paragraphs, edit.resultText, range);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 rounded-xl border border-border p-4">
      <div className="flex flex-col gap-1">
        <h3 id={headingId} className="text-sm font-semibold text-foreground">
          AI 수정안 · {formatParagraphRange(range)}
        </h3>
        <p className="text-sm break-keep text-muted-foreground">요청: {edit.instruction}</p>
      </div>

      <ComparisonBlock label="지금 글" paragraphs={original} tone="muted" />
      <ComparisonBlock label="수정안" paragraphs={candidate} tone="foreground" />

      <div className="flex flex-col gap-2">
        <p className="text-sm break-keep text-muted-foreground">버려도 쓴 클로버는 돌아오지 않아요.</p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-disabled={isActing}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (isActing) return;
              onDismiss();
            }}
          >
            버리기
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            aria-disabled={isActing}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (isActing) return;
              onApply();
            }}
          >
            적용
          </Button>
        </div>
      </div>
    </section>
  );
}

function ComparisonBlock({
  label,
  paragraphs,
  tone,
}: {
  label: string;
  paragraphs: readonly string[];
  tone: "muted" | "foreground";
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div
        className={
          tone === "muted"
            ? "flex flex-col gap-3 whitespace-pre-line text-muted-foreground"
            : "flex flex-col gap-3 whitespace-pre-line text-foreground"
        }
      >
        {paragraphs.map((paragraph, index) => (
          // 같은 문장이 두 번 나오는 문단도 있어 순서로 가른다(이 목록은 그리는 동안 바뀌지 않는다).
          <p key={index}>{paragraph}</p>
        ))}
      </div>
    </div>
  );
}
