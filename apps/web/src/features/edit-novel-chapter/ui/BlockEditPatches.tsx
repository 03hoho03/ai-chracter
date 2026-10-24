import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useId, useState } from "react";

import type { PatchCardView, PatchJobView, PatchUnitView } from "../model/blockEditPatches";
import { formatParagraphIndexes } from "../model/blockSelection";

type PatchView = "candidate" | "current";

type BlockPatchCardProps = {
  card: PatchCardView;
  /** 지금 그 블록의 글. "지금 글"로 뒤집거나 쓸 수 없게 된 수정안에서 보인다. */
  currentText: string;
  /** 어떤 수정안이든 적용·버리는 중인가. 한 번에 하나만 보낸다. */
  isActing: boolean;
  onApply: (unit: PatchUnitView) => void;
  onDismiss: (unit: PatchUnitView) => void;
};

/** 여러 문단 수정안 하나 — 그 블록 자리에 문단 대신 선다. 기본은 수정안이고, "수정안 | 지금 글" 칩으로 그 자리만 원문으로
 * 뒤집는다 — 수정안이 여럿이어도 화 길이가 늘지 않고 글 흐름 그대로 결과를 읽는다. 칩은 카드마다 하나씩 켜져 있어 선택 표시가
 * 무채 `neutral` 이다(유채색 솔리드가 수정안 수만큼 생기지 않게).
 *
 * 테두리 상자는 아직 본문이 아니라는 표시다(옛 수정안 미리보기와 같은 어휘). 묶음 원소에는 자기 버튼이 없다 — 함께 적용·버리기는
 * 마지막 원소 뒤에 한 번 선다. 그 블록을 사용자가 고쳐 지금 쓸 수 없는 수정안은 칩 없이 지금 글과 까닭을 보이고 버리기만 둔다. */
export function BlockPatchCard({ card, currentText, isActing, onApply, onDismiss }: BlockPatchCardProps) {
  const headingId = useId();
  const [view, setView] = useState<PatchView>("candidate");
  const { patch, index, isApplicable, unit } = card;
  const paragraphs = isApplicable && view === "candidate" ? (patch.paragraphs ?? []) : [currentText];
  const status = toCardStatus(card);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2 rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-xs font-medium break-keep text-muted-foreground">
          {formatParagraphIndexes([index])} · {card.jobLabel === undefined ? "" : `${card.jobLabel} · `}
          {status}
        </h3>
        {isApplicable && (
          <ToggleGroup
            type="single"
            variant="neutral"
            size="sm"
            aria-label={`${formatParagraphIndexes([index])} 보기`}
            value={view}
            onValueChange={(value) => {
              // 단일 토글 그룹은 고른 칸을 다시 누르면 빈 값을 보낸다 — 보기는 늘 하나라 해제를 받지 않는다.
              if (value === "candidate" || value === "current") setView(value);
            }}
          >
            <ToggleGroupItem value="candidate">수정안</ToggleGroupItem>
            <ToggleGroupItem value="current">지금 글</ToggleGroupItem>
          </ToggleGroup>
        )}
      </div>
      <div
        className={
          isApplicable
            ? "flex flex-col gap-3 whitespace-pre-line text-foreground"
            : "flex flex-col gap-3 whitespace-pre-line text-muted-foreground"
        }
      >
        {paragraphs.map((paragraph, rank) => (
          // 한 블록을 대신하는 새 문단들이다 — 같은 문장이 둘일 수 있어 순서로 가른다(그리는 동안 바뀌지 않는다).
          <p key={rank}>{paragraph}</p>
        ))}
      </div>
      {unit !== undefined && (
        <UnitButtons
          unit={unit}
          isActing={isActing}
          applyLabel="적용"
          dismissLabel="버리기"
          onApply={onApply}
          onDismiss={onDismiss}
        />
      )}
    </section>
  );
}

/** 카드 머리의 상태 — 쓸 수 없음이 먼저다(묶음 원소여도 그 까닭이 지금 할 일을 정한다). */
function toCardStatus(card: PatchCardView): string {
  if (!card.isApplicable) return "글이 바뀌어 적용할 수 없어요";
  return card.bundleId === undefined ? "AI 수정안" : "함께 적용해야 해요";
}

/** 묶음 다시 검사(여러 문단 수정 스위치가 켜졌을 때만 넘긴다). */
type BundleRecheck = {
  /** 이 묶음을 다시 검사하는 중인가. */
  isRechecking: boolean;
  onRecheck: (unit: PatchUnitView) => void;
};

type PatchBundleRowProps = {
  unit: PatchUnitView;
  isActing: boolean;
  onApply: (unit: PatchUnitView) => void;
  onDismiss: (unit: PatchUnitView) => void;
  /** 넘기면 고친 원소가 있는 묶음에 다시 검사가 선다. 스위치가 꺼졌으면 넘기지 않는다(서버가 404 다). */
  recheck?: BundleRecheck;
};

/** 묶음의 함께 적용·함께 버리기 — 마지막 원소 카드 바로 뒤에 선다. 원소 하나라도 쓸 수 없으면 서버가 묶음째 거절하므로 함께
 * 적용을 막고 까닭을 단다. 사용자가 고친 원소가 있으면 다시 검사(무료)를 버리기 앞에 두어, 남은 수정안을 따로 적용해도 되는지
 * 물을 수 있게 한다 — 결과는 장 머리 아래 안내 줄이 말한다. */
export function PatchBundleRow({ unit, isActing, onApply, onDismiss, recheck }: PatchBundleRowProps) {
  const reasonId = useId();
  const recheckHintId = useId();
  const isRecheckShown = recheck !== undefined && unit.canRecheck;
  return (
    <div className="flex flex-col gap-1.5 py-1">
      <p className="text-sm break-keep text-muted-foreground">
        {unit.jobLabel === undefined ? "" : `${unit.jobLabel} · `}
        {formatParagraphIndexes(unit.indexes)} 수정안은 함께 적용해야 해요{unit.reason ? ` · ${unit.reason}` : ""}
      </p>
      {!unit.isApplicable && (
        <p id={reasonId} className="text-sm break-keep text-muted-foreground">
          글이 바뀐 문단이 있어 함께 적용할 수 없어요. 함께 버릴 수 있어요.
        </p>
      )}
      {isRecheckShown && (
        <p id={recheckHintId} className="text-sm break-keep text-muted-foreground">
          다시 검사하면 남은 수정안을 따로 적용해도 되는지 AI가 살펴봐요. 클로버는 쓰지 않아요.
        </p>
      )}
      <UnitButtons
        unit={unit}
        isActing={isActing}
        applyLabel="함께 적용"
        dismissLabel="함께 버리기"
        applyBlockedReasonId={unit.isApplicable ? undefined : reasonId}
        onApply={onApply}
        onDismiss={onDismiss}
        recheck={isRecheckShown ? { ...recheck, hintId: recheckHintId } : undefined}
      />
    </div>
  );
}

type PatchJobRowProps = {
  job: PatchJobView;
  /** 이 작업에 남은(대기·쓸 수 없음) 수정안 수. */
  remainingCount: number;
  isActing: boolean;
  onDismissAll: () => void;
};

/** 작업 하나의 꼬리 줄 — 요청 문장, 돌려받지 못한다는 안내, 남은 수정안 모두 버리기. 블록이 지워져 자리를 잃은 수정안은 여기서 센다. */
export function PatchJobRow({ job, remainingCount, isActing, onDismissAll }: PatchJobRowProps) {
  return (
    <div className="flex flex-col gap-1.5 py-1">
      <p className="text-sm break-keep text-muted-foreground">
        {job.jobLabel ?? "요청"}: {job.instruction}
      </p>
      {job.unplacedUnits.length > 0 && (
        <p className="text-sm break-keep text-muted-foreground">
          문단이 지워져 자리를 잃은 수정안이 {job.unplacedUnits.reduce((count, unit) => count + unit.patchIds.length, 0)}개 있어요.
        </p>
      )}
      <p className="text-sm break-keep text-muted-foreground">버려도 쓴 클로버는 돌아오지 않아요.</p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-disabled={isActing}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (isActing) return;
            onDismissAll();
          }}
        >
          {job.jobLabel === undefined ? "" : `${job.jobLabel} `}남은 수정안 모두 버리기 ({remainingCount}개)
        </Button>
      </div>
    </div>
  );
}

type UnitButtonsProps = {
  unit: PatchUnitView;
  isActing: boolean;
  applyLabel: string;
  dismissLabel: string;
  /** 적용을 막는 까닭 문장의 id. 있으면 적용이 막힌다. */
  applyBlockedReasonId?: string;
  onApply: (unit: PatchUnitView) => void;
  onDismiss: (unit: PatchUnitView) => void;
  /** 있으면 버리기 앞에 다시 검사가 선다. `hintId` 는 무엇을 하는지 적은 문장. */
  recheck?: BundleRecheck & { hintId: string };
};

/** 버리기 먼저(확인 단계의 `취소` 먼저와 같은 자리), 적용은 회색 채움. 쓸 수 없는 독립 수정안에는 적용이 없다. 다시 검사는 가장
 * 앞의 테두리 없는 버튼이다(무료 보조 동작). 보내는 동안은 `aria-disabled` 로 막아 누른 버튼의 포커스를 지킨다. */
function UnitButtons({
  unit,
  isActing,
  applyLabel,
  dismissLabel,
  applyBlockedReasonId,
  onApply,
  onDismiss,
  recheck,
}: UnitButtonsProps) {
  const isApplyBlocked = isActing || applyBlockedReasonId !== undefined;
  return (
    <div className="flex flex-wrap gap-2">
      {recheck !== undefined && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-disabled={isActing}
          aria-describedby={recheck.hintId}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (isActing) return;
            recheck.onRecheck(unit);
          }}
        >
          {recheck.isRechecking ? "다시 검사하는 중…" : "다시 검사(무료)"}
        </Button>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={isActing}
        className="aria-disabled:opacity-65"
        onClick={() => {
          if (isActing) return;
          onDismiss(unit);
        }}
      >
        {dismissLabel}
      </Button>
      {(unit.isApplicable || unit.isBundle) && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          aria-disabled={isApplyBlocked}
          aria-describedby={applyBlockedReasonId}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (isApplyBlocked) return;
            onApply(unit);
          }}
        >
          {applyLabel}
        </Button>
      )}
    </div>
  );
}
