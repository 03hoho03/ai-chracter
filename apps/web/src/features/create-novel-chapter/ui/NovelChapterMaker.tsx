import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Loader2 } from "lucide-react";
import { useId, useRef } from "react";

import { NOVEL_ROOM_GONE_MESSAGE } from "@/entities/novel";

import type { NovelChapterJobFlow } from "../model/useNovelChapterJob";

type NovelChapterMakerProps = {
  flow: NovelChapterJobFlow;
  hasChapters: boolean;
};

/** "다음 장 만들기" 버튼과 그 작업의 진행·결과 안내.
 *
 * - 못 누르는 동안에도 버튼은 `disabled` 가 아니라 `aria-disabled` 다 — `disabled` 는 누른 순간 포커스를 날리고,
 *   왜 못 누르는지를 알려 주지 않는다. 이유는 버튼 바로 아래 문장(대화방이 지워짐·AI 수정 중)이나 진행 줄이 진다.
 * - 진행 줄은 언제나 마운트돼 있는 `aria-live` 다 — 조건부로 붙이면 붙는 순간의 문장을 화면 낭독기가 놓친다.
 *   스피너는 진행 표시라 동작 줄이기 설정에서도 돈다(멈추면 멈춘 화면으로 읽힌다).
 * - 실패 안내는 `role="alert"` 상자이고, 다시 시도할 수 있는 실패면 그 안에 버튼을 둔다. 결과 문장은 훅이 기록한
 *   상태라 상세를 다시 받아도 사라지지 않는다. 새 장에 번쩍이는 강조를 두지 않는다 — 어두운 방에서 갑작스러운
 *   밝기 변화는 놀람이고, 새 장 제목으로 옮긴 포커스가 위치를 알린다. */
export function NovelChapterMaker({ flow, hasChapters }: NovelChapterMakerProps) {
  const reasonId = useId();
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const blockedReason = toBlockedReason(flow);
  const isBlocked = flow.isBusy || flow.isRoomGone;
  const describedBy = blockedReason !== undefined ? reasonId : runningStatusId(flow);
  const isPreparingCreate = flow.preparing === "create";
  const label = hasChapters ? "다음 장 만들기" : "첫 장 만들기";

  return (
    <section aria-label="장 만들기" className="flex flex-col gap-3">
      <div className="flex flex-col items-start gap-2">
        <Button
          ref={createButtonRef}
          type="button"
          aria-disabled={isBlocked}
          aria-describedby={describedBy}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (isBlocked) return;
            void flow.startCreate();
          }}
        >
          {/* 두 라벨을 한 칸에 겹쳐 지금 아닌 쪽만 감춘다 — 라벨이 바뀌어도 버튼 폭이 그대로다. `invisible` 은 접근성
              트리에서도 빠져 이름은 보이는 라벨 하나다. */}
          <span className="grid">
            <span className={cn("col-start-1 row-start-1", isPreparingCreate && "invisible")}>{label}</span>
            <span
              className={cn(
                "col-start-1 row-start-1 inline-flex items-center justify-center gap-1.5",
                !isPreparingCreate && "invisible",
              )}
            >
              <Loader2 aria-hidden className="animate-spin" />
              준비 중…
            </span>
          </span>
        </Button>
        {blockedReason !== undefined && (
          <p id={reasonId} className="text-sm break-keep text-muted-foreground">
            {blockedReason}
          </p>
        )}
      </div>

      <p id={flow.statusId} aria-live="polite" aria-atomic className="flex items-center gap-2 text-sm break-keep text-muted-foreground">
        {flow.isJobRunning && <Loader2 aria-hidden className="size-4 shrink-0 animate-spin" />}
        {toStatusText(flow)}
      </p>

      {flow.notice?.tone === "error" && (
        <div role="alert" className="flex flex-col items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          <p>{flow.notice.message}</p>
          {flow.notice.retry !== undefined && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-disabled={flow.isBusy}
              className="aria-disabled:opacity-65"
              onClick={() => {
                if (flow.isBusy || flow.notice?.tone !== "error" || flow.notice.retry === undefined) return;
                // 다시 시도하면 이 안내 상자가 사라진다 — 누른 버튼과 함께 포커스가 `<body>` 로 떨어지지 않게, 남아
                // 있는 만들기 버튼으로 먼저 옮긴다.
                createButtonRef.current?.focus();
                flow.retry(flow.notice.retry);
              }}
            >
              다시 시도
            </Button>
          )}
        </div>
      )}
    </section>
  );
}

/** 버튼 바로 아래에 둘 "왜 못 누르나". 장 작업이 도는 중이면 여기 말고 진행 줄이 그 몫을 진다. */
function toBlockedReason(flow: NovelChapterJobFlow): string | undefined {
  if (flow.isRoomGone) return NOVEL_ROOM_GONE_MESSAGE;
  if (flow.isAiEditRunning) return "AI로 고치는 중이에요. 끝나면 새 장을 만들 수 있어요.";
  return undefined;
}

function runningStatusId(flow: NovelChapterJobFlow): string | undefined {
  return flow.isJobRunning ? flow.statusId : undefined;
}

function toStatusText(flow: NovelChapterJobFlow): string {
  if (flow.isJobRunning) {
    if (flow.hasPollError) return "진행 상황을 확인하지 못하고 있어요. 잠시 뒤 다시 확인할게요.";
    const subject =
      flow.runningKind === "chapter_regenerate"
        ? `${flow.runningChapterOrdinal === undefined ? "장" : `${flow.runningChapterOrdinal}장`}을 다시 쓰고 있어요.`
        : "새 장을 쓰고 있어요.";
    return `${subject} 이 화면을 떠나도 계속 써요.`;
  }
  return flow.notice?.tone === "done" ? flow.notice.message : "";
}
