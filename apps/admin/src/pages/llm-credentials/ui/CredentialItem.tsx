import { Button } from "@ai-character-chat/ui/components/button";
import { ArrowDown, ArrowUp, KeyRound } from "lucide-react";
import type { ReactNode } from "react";

import { formatMonthDayTime } from "@/shared/lib/format/formatDateTime";

import type { AdminLlmCredential } from "../model/credential";
import { BEDROCK_UNSUPPORTED_TEXT, enableBlockerText, PROVIDER_LABELS } from "../model/labels";
import type { CredentialStatus, MoveDirection } from "../model/status";
import { NEUTRAL_BADGE_CLASS, TYPE_BADGE_CLASS } from "./badgeClasses";
import { CheckResults, type CheckLock } from "./CheckResults";
import { CredentialStatusBadge } from "./CredentialStatusBadge";
import {
  checkButtonId,
  credentialHeadingId,
  enableBlockerId,
  moveButtonId,
  providerNoteId,
  STORE_NOTICE_ID,
} from "./elementIds";
import { SpendSummary } from "./SpendSummary";

type CredentialItemProps = {
  credential: AdminLlmCredential;
  /** 1부터 센 목록 위치. 행 버튼 접근 이름에 넣는다 — 서버가 이름의 유일성을 지키지 않아 이름만으로는 같은 버튼이 둘이 될 수 있다. */
  position: number;
  total: number;
  status: CredentialStatus;
  modelIds: Readonly<Record<string, string>>;
  isStoreMissing: boolean;
  /** 순서 저장 중이거나 목록을 다시 받는 중이라 위·아래를 누를 수 없다(같은 판으로 두 번, 곧 바뀔 판으로 보내지 않게). */
  isOrderLocked: boolean;
  isStatePending: boolean;
  checkLock: CheckLock;
  checkNotice: ReactNode;
  onMove: (direction: MoveDirection) => void;
  onToggleState: () => void;
  onCheck: () => void;
  onEdit: () => void;
  onCreditBasis: () => void;
  onReplaceSecret: () => void;
  onDelete: () => void;
};

/** 순서 목록의 항목 하나. 채움 없는 윤곽 상자다 — 안에 윤곽 버튼이 있어 채우면 그 버튼 테두리가 대비를 잃는다. 확인·사용액 두 블록은
 * 뷰포트가 아니라 항목 폭으로 가른다(사이드바 접힘에 따라 폭이 바뀐다). */
export function CredentialItem({
  credential,
  position,
  total,
  status,
  modelIds,
  isStoreMissing,
  isOrderLocked,
  isStatePending,
  checkLock,
  checkNotice,
  onMove,
  onToggleState,
  onCheck,
  onEdit,
  onCreditBasis,
  onReplaceSecret,
  onDelete,
}: CredentialItemProps) {
  const { id, label } = credential;
  const itemName = `${position}번째 ${label}`;
  const isAnthropic = credential.provider === "anthropic";
  const toggle = toggleAction(credential, isStatePending);
  const isToggleBlocked = toggle.blocker !== null;
  const isSecretBlocked = isStoreMissing || !isAnthropic;

  const handleMove = (direction: MoveDirection) => {
    if (!isOrderLocked) onMove(direction);
  };

  return (
    <li aria-labelledby={credentialHeadingId(id)} className="@container flex flex-col gap-4 rounded-xl border border-border p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex gap-1">
          <Button
            id={moveButtonId(id, "up")}
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label={`${itemName} 한 칸 위로`}
            // 첫 항목의 위는 늘 할 수 없는 일이라 Tab 정지에서 빠져도 된다. 저장 중 잠금은 누른 버튼이 포커스를 잃지 않게 aria 로 건다.
            disabled={position === 1}
            aria-disabled={isOrderLocked}
            className="aria-disabled:opacity-65"
            onClick={() => handleMove("up")}
          >
            <ArrowUp aria-hidden />
          </Button>
          <Button
            id={moveButtonId(id, "down")}
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label={`${itemName} 한 칸 아래로`}
            disabled={position === total}
            aria-disabled={isOrderLocked}
            className="aria-disabled:opacity-65"
            onClick={() => handleMove("down")}
          >
            <ArrowDown aria-hidden />
          </Button>
        </div>
        <span aria-hidden className="text-lg font-semibold tabular-nums text-muted-foreground">
          {position}
        </span>
        <h3
          id={credentialHeadingId(id)}
          tabIndex={-1}
          className="min-w-0 break-keep text-lg font-semibold text-foreground outline-none wrap-anywhere"
        >
          {label}
        </h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={TYPE_BADGE_CLASS}>{PROVIDER_LABELS[credential.provider]}</span>
          <CredentialStatusBadge status={status} />
          {credential.sameAsEnvKey && (
            <span className={NEUTRAL_BADGE_CLASS}>
              <KeyRound aria-hidden className="size-3" />
              env 롤백 키와 같은 키
            </span>
          )}
        </div>
      </div>

      <p className="text-xs text-muted-foreground wrap-anywhere">
        {credential.accountRef === null ? "조직 미확인" : `조직 ${credential.accountRef}`} · 키 끝 ····
        {credential.secretLast4} · 지문 {credential.secretFingerprint} · 상태 바뀜{" "}
        {formatMonthDayTime(credential.stateChangedAt)}
      </p>

      <div className="grid gap-4 @2xl:grid-cols-2">
        <CheckResults
          credential={credential}
          itemName={itemName}
          modelIds={modelIds}
          lock={checkLock}
          onCheck={onCheck}
          notice={checkNotice}
        />
        <SpendSummary credential={credential} itemName={itemName} onCreditBasis={onCreditBasis} />
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label={`${itemName} ${toggle.name}`}
            aria-disabled={isToggleBlocked || isStatePending}
            aria-describedby={isToggleBlocked ? enableBlockerId(id) : undefined}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (!isToggleBlocked && !isStatePending) onToggleState();
            }}
          >
            {isStatePending ? `${toggle.name}…` : toggle.name}
          </Button>
          <Button type="button" variant="outline" size="sm" aria-label={`${itemName} 이름·임계 수정`} onClick={onEdit}>
            이름·임계 수정…
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label={`${itemName} 키 교체`}
            aria-disabled={isSecretBlocked}
            aria-describedby={secretBlockDescriptionId(id, isStoreMissing, isAnthropic)}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (!isSecretBlocked) onReplaceSecret();
            }}
          >
            키 교체…
          </Button>
          <Button type="button" variant="destructive" size="sm" aria-label={`${itemName} 삭제`} onClick={onDelete}>
            삭제…
          </Button>
        </div>
        {toggle.blocker !== null && (
          <p id={enableBlockerId(id)} className="break-keep text-sm text-destructive-text">
            {enableBlockerText(toggle.blocker, credential.state)}
            {toggle.blocker === "check-required" && (
              <>
                {" "}
                <button
                  type="button"
                  aria-label={`${itemName} 확인 호출 버튼으로 가기`}
                  className="admin-hit-area rounded-sm font-medium underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  onClick={() => document.getElementById(checkButtonId(id))?.focus()}
                >
                  확인 호출
                </button>
              </>
            )}
          </p>
        )}
        {!isAnthropic && (
          <p id={providerNoteId(id)} className="break-keep text-xs text-muted-foreground">
            {BEDROCK_UNSUPPORTED_TEXT}
          </p>
        )}
      </div>
    </li>
  );
}

/** 켜기 버튼의 글자는 상태로 정한다. 켜기·다시 켜기는 서버가 미리 계산한 막힘이 있으면 누를 수 없다(끄기는 늘 된다). 보내는 동안은
 * 보이는 글자와 접근 이름이 함께 "…하는 중"이 된다. */
function toggleAction(credential: AdminLlmCredential, isPending: boolean) {
  switch (credential.state) {
    case "active":
      return { name: isPending ? "끄는 중" : "끄기", blocker: null };
    case "exhausted":
      return { name: isPending ? "켜는 중" : "다시 켜기", blocker: credential.enableBlocker };
    case "disabled":
      return { name: isPending ? "켜는 중" : "켜기", blocker: credential.enableBlocker };
    default:
      return assertNever(credential.state);
  }
}

function secretBlockDescriptionId(credentialId: string, isStoreMissing: boolean, isAnthropic: boolean) {
  if (!isAnthropic) return providerNoteId(credentialId);
  return isStoreMissing ? STORE_NOTICE_ID : undefined;
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 상태: ${String(value)}`);
}
