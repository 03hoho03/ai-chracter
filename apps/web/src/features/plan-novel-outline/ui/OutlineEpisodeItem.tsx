import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ArrowDown, ArrowUp, ChevronDown, Combine, Ellipsis, Pencil, Scissors, Trash2 } from "lucide-react";
import { Fragment, useId, useState, type ReactNode } from "react";

import {
  toBasisLabel,
  toEpisodeTurns,
  toSplitPoints,
  type OutlineEpisodeDraft,
  type OutlineEpisodeText,
  type TurnIndex,
} from "../model/outlineEdits";

import { OutlineEpisodeForm } from "./OutlineEpisodeForm";

/** 근거 대화 목록을 그릴 수 있는가 — 대화를 받았나·받는 중인가·못 받았나·방이 지워졌나. */
export type OutlineTurnsStatus = "ready" | "loading" | "error" | "gone";

type OutlineEpisodeItemProps = {
  episode: OutlineEpisodeDraft;
  ordinal: number;
  index: number;
  count: number;
  turnIndex: TurnIndex | undefined;
  turnsStatus: OutlineTurnsStatus;
  /** 이 구성안을 지금 고칠 수 있는가(낡음·방 없음·구성안 작업 중이면 아니다). 아니면 고치기·메뉴가 없다. */
  canEdit: boolean;
  isEditing: boolean;
  isSplitting: boolean;
  /** 다음 화와 합치지 못하는 이유. 없으면 합칠 수 있다. */
  mergeBlockedReason: string | undefined;
  titleMaxLength: number;
  onEdit: () => void;
  onApply: (text: OutlineEpisodeText) => void;
  onCancelEdit: () => void;
  onMove: (delta: -1 | 1) => void;
  onMerge: () => void;
  onStartSplit: () => void;
  onCancelSplit: () => void;
  onSplit: (cutMessageId: string) => void;
  onRemove: () => void;
};

/**
 * 구성안 화 하나 — 화 번호·제목·줄거리·목표와 근거 대화. 근거 대화는 접혀 있다가 "근거 n~m턴"을 누르면 턴마다 두 줄 발췌로 펼친다.
 * 근거는 직접 끌어 고치지 않는다 — 이웃 화와 합치거나 턴 사이에서 나누는 것으로만 바뀐다(어느 턴이든 한 화에만, 턴은 가르지 않음).
 *
 * 구조 바꾸기(차례·합치기·나누기·지우기)는 "⋯" 메뉴에 모은다. 못 하는 항목은 메뉴에 남겨 두고 `aria-disabled` + 바로 아래 이유 줄을
 * 단다. 원고가 있는 화는 고치지 않는다.
 */
export function OutlineEpisodeItem({
  episode,
  ordinal,
  index,
  count,
  turnIndex,
  turnsStatus,
  canEdit,
  isEditing,
  isSplitting,
  mergeBlockedReason,
  titleMaxLength,
  onEdit,
  onApply,
  onCancelEdit,
  onMove,
  onMerge,
  onStartSplit,
  onCancelSplit,
  onSplit,
  onRemove,
}: OutlineEpisodeItemProps) {
  const headingId = useId();
  const basisListId = useId();
  const [isBasisOpen, setIsBasisOpen] = useState(false);
  const label = `${ordinal}화`;
  const isWritten = episode.chapterId !== null;
  const isEditable = canEdit && !isWritten;
  const basisLabel = turnIndex === undefined ? undefined : toBasisLabel(turnIndex, episode.basis);
  const turns = turnIndex === undefined ? undefined : toEpisodeTurns(turnIndex, episode.basis);
  const splitPoints = turnIndex === undefined ? [] : toSplitPoints(turnIndex, episode.basis);
  const splitBlockedReason = toSplitBlockedReason(turnsStatus, turns !== undefined, splitPoints.length);

  return (
    <li
      aria-labelledby={headingId}
      data-outline-episode={episode.localId}
      className="flex flex-col gap-3 rounded-xl border border-border px-4 py-4"
    >
      <div className="flex items-start gap-2">
        <h4 id={headingId} className="min-w-0 flex-1 text-base font-semibold break-keep text-foreground">
          <span className="text-muted-foreground tabular-nums">{label}</span> · {episode.title.trim() === "" ? "제목 없음" : episode.title}
        </h4>
        {isWritten && (
          <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
            원고 있음
          </span>
        )}
        {episode.key === null && (
          <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
            나눈 화
          </span>
        )}
        {isEditable && !isEditing && (
          <div className="-my-1 flex shrink-0 items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`${label} 고치기`}
              data-outline-edit={episode.localId}
              onClick={onEdit}
            >
              <Pencil aria-hidden />
            </Button>
            <EpisodeMenu
              label={label}
              localId={episode.localId}
              index={index}
              count={count}
              mergeBlockedReason={mergeBlockedReason}
              splitBlockedReason={splitBlockedReason}
              onMove={onMove}
              onMerge={onMerge}
              onStartSplit={onStartSplit}
              onRemove={onRemove}
            />
          </div>
        )}
      </div>

      {isEditing ? (
        <OutlineEpisodeForm
          label={label}
          initial={{ title: episode.title, summary: episode.summary, goal: episode.goal }}
          titleMaxLength={titleMaxLength}
          onApply={onApply}
          onCancel={onCancelEdit}
        />
      ) : (
        <>
          <p className="text-sm whitespace-pre-line text-pretty break-keep text-foreground">{episode.summary}</p>
          {episode.goal.trim() !== "" && (
            <p className="text-sm whitespace-pre-line break-keep text-muted-foreground">
              <span className="font-medium text-foreground">목표</span> · {episode.goal}
            </p>
          )}
        </>
      )}

      {isSplitting && turns !== undefined ? (
        <SplitPicker
          label={label}
          turns={turns}
          splitAfter={new Map(splitPoints.map((point) => [point.afterTurnNumber, point.cutMessageId]))}
          onSplit={onSplit}
          onCancel={onCancelSplit}
        />
      ) : (
        <div className="flex flex-col gap-2">
          <BasisToggle
            status={turnsStatus}
            basisLabel={basisLabel}
            isOpen={isBasisOpen}
            controlsId={basisListId}
            onToggle={() => setIsBasisOpen((open) => !open)}
          />
          {isBasisOpen && turns !== undefined && (
            <ol id={basisListId} aria-label={`${label} 근거 대화`} className="flex flex-col gap-1">
              {turns.map((turn) => (
                <li key={turn.key}>
                  <TurnLine number={turn.number} excerpt={turn.excerpt} />
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  );
}

function toSplitBlockedReason(status: OutlineTurnsStatus, hasTurns: boolean, pointCount: number): string | undefined {
  if (status === "gone") return "원래 대화방이 지워져 나눌 수 없어요.";
  if (status !== "ready") return "대화를 불러온 뒤 나눌 수 있어요.";
  if (!hasTurns) return "근거 대화 일부가 지워져 나눌 수 없어요.";
  if (pointCount === 0) return "턴이 하나뿐이라 나눌 곳이 없어요.";
  return undefined;
}

type BasisToggleProps = {
  status: OutlineTurnsStatus;
  basisLabel: string | undefined;
  isOpen: boolean;
  controlsId: string;
  onToggle: () => void;
};

/** 근거 대화를 펼치는 버튼. 대화를 아직 못 받았거나 근거 메시지를 못 찾으면 버튼 대신 그 사정을 한 줄로 말한다. */
function BasisToggle({ status, basisLabel, isOpen, controlsId, onToggle }: BasisToggleProps) {
  if (status === "gone") return <p className="text-xs text-muted-foreground">원래 대화방이 지워져 근거 대화를 볼 수 없어요.</p>;
  if (status === "loading") return <p className="text-xs text-muted-foreground">근거 대화를 불러오는 중이에요.</p>;
  if (status === "error") return <p className="text-xs text-muted-foreground">근거 대화를 불러오지 못했어요.</p>;
  if (basisLabel === undefined) {
    return <p className="text-xs text-muted-foreground">근거 대화 일부가 지금 대화방에 없어요(지워졌거나 다시 쓰였어요).</p>;
  }
  return (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      className="-ml-2 self-start text-muted-foreground"
      aria-expanded={isOpen}
      aria-controls={isOpen ? controlsId : undefined}
      onClick={onToggle}
    >
      근거 {basisLabel}
      <ChevronDown aria-hidden className={cn("motion-safe:transition-transform", isOpen && "rotate-180")} />
    </Button>
  );
}

function TurnLine({ number, excerpt }: { number: number; excerpt: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border px-3 py-2">
      <span className="text-xs text-muted-foreground tabular-nums">{number}턴</span>
      <span className="line-clamp-2 text-sm break-keep text-foreground">{excerpt === "" ? "(빈 메시지)" : excerpt}</span>
    </div>
  );
}

type SplitPickerProps = {
  label: string;
  turns: readonly { key: string; number: number; excerpt: string }[];
  /** 그 턴 뒤에서 나눌 수 있으면 자를 메시지 id. */
  splitAfter: ReadonlyMap<number, string>;
  onSplit: (cutMessageId: string) => void;
  onCancel: () => void;
};

/** 나눌 자리 고르기 — 근거 턴 사이마다 "n턴 뒤에서 나누기". 나눌 수 없는 사이(앞 턴이 응답 없이 끝남)에는 버튼이 없다. */
function SplitPicker({ label, turns, splitAfter, onSplit, onCancel }: SplitPickerProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="min-w-0 flex-1 text-sm break-keep text-foreground">
          {label}을 나눌 자리를 고르세요. 그 턴까지가 앞 화, 다음 턴부터가 새 화예요.
        </p>
        <Button type="button" variant="ghost" size="xs" data-outline-split-cancel onClick={onCancel}>
          나누기 취소
        </Button>
      </div>
      <ol aria-label={`${label} 나눌 자리`} className="flex flex-col gap-1">
        {turns.map((turn) => {
          const cut = splitAfter.get(turn.number);
          return (
            <Fragment key={turn.key}>
              <li>
                <TurnLine number={turn.number} excerpt={turn.excerpt} />
              </li>
              {cut !== undefined && (
                <li className="flex items-center gap-2 py-0.5">
                  <span aria-hidden className="h-px flex-1 border-t border-dashed border-border" />
                  <Button type="button" variant="outline" size="xs" onClick={() => onSplit(cut)}>
                    <Scissors aria-hidden />
                    {turn.number}턴 뒤에서 나누기
                  </Button>
                  <span aria-hidden className="h-px flex-1 border-t border-dashed border-border" />
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </div>
  );
}

type EpisodeMenuProps = {
  label: string;
  localId: string;
  index: number;
  count: number;
  mergeBlockedReason: string | undefined;
  splitBlockedReason: string | undefined;
  onMove: (delta: -1 | 1) => void;
  onMerge: () => void;
  onStartSplit: () => void;
  onRemove: () => void;
};

function EpisodeMenu({
  label,
  localId,
  index,
  count,
  mergeBlockedReason,
  splitBlockedReason,
  onMove,
  onMerge,
  onStartSplit,
  onRemove,
}: EpisodeMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon-sm" aria-label={`${label} 구성 바꾸기`} data-outline-menu={localId}>
          <Ellipsis aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto">
        <MenuAction
          icon={<ArrowUp aria-hidden />}
          blockedReason={index === 0 ? "맨 앞 화예요." : undefined}
          onSelect={() => onMove(-1)}
        >
          위로 옮기기
        </MenuAction>
        <MenuAction
          icon={<ArrowDown aria-hidden />}
          blockedReason={index === count - 1 ? "맨 뒤 화예요." : undefined}
          onSelect={() => onMove(1)}
        >
          아래로 옮기기
        </MenuAction>
        <DropdownMenuSeparator />
        <MenuAction icon={<Combine aria-hidden />} blockedReason={mergeBlockedReason} onSelect={onMerge}>
          다음 화와 합치기
        </MenuAction>
        <MenuAction icon={<Scissors aria-hidden />} blockedReason={splitBlockedReason} onSelect={onStartSplit}>
          나누기
        </MenuAction>
        <DropdownMenuSeparator />
        <MenuAction
          icon={<Trash2 aria-hidden />}
          variant="destructive"
          blockedReason={count <= 1 ? "구성안에는 화가 하나 이상 있어야 해요." : undefined}
          onSelect={onRemove}
        >
          지우기
        </MenuAction>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

type MenuActionProps = {
  icon: ReactNode;
  blockedReason: string | undefined;
  variant?: "default" | "destructive";
  onSelect: () => void;
  children: ReactNode;
};

/** 메뉴 항목 하나. 못 하면 `disabled` 가 아니라 `aria-disabled` 로 순회에 남기고, 이유를 바로 아래 줄에 둔다(구분선 없이 — 위 항목의
 * 설명이라서). */
function MenuAction({ icon, blockedReason, variant = "default", onSelect, children }: MenuActionProps) {
  const reasonId = useId();
  const isBlocked = blockedReason !== undefined;
  return (
    <>
      <DropdownMenuItem
        variant={variant}
        aria-disabled={isBlocked || undefined}
        aria-describedby={isBlocked ? reasonId : undefined}
        onSelect={(event) => {
          if (isBlocked) {
            event.preventDefault();
            return;
          }
          onSelect();
        }}
      >
        {icon}
        {children}
      </DropdownMenuItem>
      {isBlocked && (
        <DropdownMenuLabel id={reasonId} className="max-w-60 pt-0 text-xs font-normal break-keep text-muted-foreground">
          {blockedReason}
        </DropdownMenuLabel>
      )}
    </>
  );
}
