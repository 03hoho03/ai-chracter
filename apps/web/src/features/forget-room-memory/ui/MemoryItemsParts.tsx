import type { Ref } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { CircleCheck, CircleSlash, Info } from "lucide-react";

import { koreanParticle } from "@/shared/lib/text/koreanParticle";

import { MEMORY_COMEBACK_NOTICE, usedInRepliesText } from "../model/memoryItemText";
import { MemoryNote } from "./MemoryNote";

/** 목록 위에 남기는 잊게 하기 결과. `forgotten`은 요약 편집으로 잇는다 — 장면·사실을 지워도 요약에 같은 내용이 남을 수
 * 있고, 요약은 사용자가 직접 고칠 수 있다. */
export type MemoryListNotice =
  | { kind: "forgotten"; label: string; linkedEpisodeCount: number }
  | { kind: "message"; message: string };

type ForgetResultNoticeProps = {
  ref: Ref<HTMLDivElement>;
  notice: MemoryListNotice;
  onEditSummaryRequest: () => void;
};

/** 잊게 한 행은 사라지므로 확인 대화가 닫히면 포커스가 돌아갈 곳이 없다 — 이 알림이 포커스를 받는다(`tabIndex=-1`). */
export function ForgetResultNotice({ ref, notice, onEditSummaryRequest }: ForgetResultNoticeProps) {
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="status"
      className="rounded-lg border border-border px-3.5 py-2.5 text-xs break-keep text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {notice.kind === "message" ? (
        notice.message
      ) : (
        <>
          ‘{notice.label}’{koreanParticle(notice.label, "을/를")} 잊게 했어요.
          {notice.linkedEpisodeCount > 0 && ` 이어진 장면 ${notice.linkedEpisodeCount}개도 함께 잊었어요.`} 요약에 같은
          내용이 남아 있으면{" "}
          {/* 문장 속 링크라 쉬는 상태에도 밑줄을 두고, 포커스는 띄운 아웃라인으로 준다(밑줄이 이미 있어 밑줄 포커스는 바뀌는
              것이 없다). */}
          <button
            type="button"
            onClick={onEditSummaryRequest}
            className="rounded-sm font-medium text-primary underline underline-offset-4 outline-none focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
          >
            요약 고치기
          </button>
          로 지워 주세요.
        </>
      )}
    </div>
  );
}

export function UsedInRepliesLine({ kind, isUsed }: { kind: "episodes" | "facts"; isUsed: boolean }) {
  return (
    <MemoryNote icon={isUsed ? CircleCheck : CircleSlash} isEmphasized={isUsed}>
      {usedInRepliesText(kind, isUsed)}
    </MemoryNote>
  );
}

export function MemoryComebackNote() {
  return <MemoryNote icon={Info}>{MEMORY_COMEBACK_NOTICE}</MemoryNote>;
}

/** 첫 페이지를 받는 동안의 자리. 진행 표시라 줄인 모션에서도 깜빡인다. 채움은 `secondary` — 이 목록이 놓이는 카드·대화
 * 상자 표면에서 `muted`는 사라진다. */
export function MemoryItemsSkeleton() {
  return (
    <div className="flex flex-col" aria-busy="true">
      <span className="sr-only">불러오는 중…</span>
      {[0, 1, 2].map((index) => (
        <div key={index} aria-hidden className="flex flex-col gap-2 border-b border-border py-3 last:border-b-0">
          <div className="h-4 w-1/2 animate-pulse rounded bg-secondary" />
          <div className="h-4 w-full animate-pulse rounded bg-secondary" />
        </div>
      ))}
    </div>
  );
}

export function MemoryItemsLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6">
      <p className="text-sm break-keep text-muted-foreground">기억을 불러오지 못했어요.</p>
      <Button type="button" variant="outline" className="hover:bg-secondary" onClick={onRetry}>
        다시 시도
      </Button>
    </div>
  );
}

export function MemoryItemsEmpty({ children }: { children: string }) {
  return (
    <p className="rounded-lg border border-dashed border-border px-3.5 py-3 text-sm break-keep text-muted-foreground">
      {children}
    </p>
  );
}
