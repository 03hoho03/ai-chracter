import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Fragment, type ReactNode } from "react";

import { formatMonthDayTime } from "@/shared/lib/format/formatDateTime";

import { AXIS_LABELS } from "../model/axes";
import { checkCallCount } from "../model/checkCall";
import type { AdminLlmCredential, AdminLlmCredentialCheckItem } from "../model/credential";
import {
  checkVerdictText,
  ENABLE_NEEDS_CONCLUSIVE_TEXT,
  modelIdChangedText,
  NO_CHECKS_TEXT,
  OLD_SECRET_CHECK_TEXT,
  OLD_STATE_CHECK_TEXT,
  TRANSIENT_RETRY_HINT_TEXT,
  TRANSIENT_WITH_PREVIOUS_TEXT,
  TRANSIENT_WITHOUT_PREVIOUS_TEXT,
} from "../model/labels";
import { axisCheckRows, latestCheck, type AxisCheckRows } from "../model/status";
import { checkButtonId, checkHintId, providerNoteId, STORE_NOTICE_ID } from "./elementIds";

/** 확인 호출 버튼이 막힌 이유. 진행 중·잠금은 버튼 아래 문장이, 저장소·공급자는 그 자리의 안내 문장이 설명한다. */
export type CheckLock =
  | { kind: "open" }
  | { kind: "store-missing" }
  | { kind: "provider" }
  | { kind: "checking" }
  | { kind: "cooldown" };

type CheckResultsProps = {
  credential: AdminLlmCredential;
  /** 행 버튼 접근 이름의 앞머리("2번째 운영 계정"). */
  itemName: string;
  modelIds: Readonly<Record<string, string>>;
  lock: CheckLock;
  onCheck: () => void;
  /** 확인 뒤 결과 안내·확인 실패 문장 자리. */
  notice: ReactNode;
};

/**
 * 확인 블록. 축마다 최신 결과를 보이고, 최신이 일시 오류면 런타임이 그대로 쓰는 이전 결과를 함께 보인다. 받을 수 있는 축 자체는 상태
 * 표지가 `runtimeAxes` 로 말한다 — 여기 행이 통과여도 그 축을 받지 않을 수 있고(풀리지 않은 조직 신호), 그 이유는 켤 수 없는 이유
 * 문장이 설명한다.
 */
export function CheckResults({ credential, itemName, modelIds, lock, onCheck, notice }: CheckResultsProps) {
  const latest = latestCheck(credential.checks);
  const isChecking = lock.kind === "checking";
  const callCount = checkCallCount(modelIds);

  return (
    <div className="flex min-w-0 flex-col items-start gap-2">
      <h4 className="text-sm font-semibold text-foreground">확인</h4>
      {latest === undefined ? (
        <p className="break-keep text-sm text-muted-foreground">{NO_CHECKS_TEXT}</p>
      ) : (
        <>
          <p className="text-xs tabular-nums text-muted-foreground">
            마지막 확인 {formatMonthDayTime(latest.checkedAt)} · {latest.run}번째
          </p>
          <dl className="grid w-full grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
            {axisCheckRows(credential.checks).map((rows) => (
              <AxisResult key={rows.axis} rows={rows} currentModelId={modelIds[rows.axis]} />
            ))}
          </dl>
          {checkNotes(credential, latest).map((note) => (
            <p key={note} className="break-keep text-xs text-muted-foreground">
              {note}
            </p>
          ))}
        </>
      )}
      <div className="flex flex-col items-start gap-1">
        <Button
          id={checkButtonId(credential.id)}
          type="button"
          variant="outline"
          size="sm"
          aria-label={`${itemName} ${isChecking ? "확인하는 중" : "확인 호출"}`}
          aria-disabled={lock.kind !== "open"}
          aria-describedby={lockDescriptionId(credential.id, lock)}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (lock.kind === "open") onCheck();
          }}
        >
          {isChecking ? "확인하는 중…" : "확인 호출"}
        </Button>
        <p id={checkHintId(credential.id)} className="break-keep text-xs text-muted-foreground">
          {checkHint(lock, callCount)}
        </p>
      </div>
      {notice}
    </div>
  );
}

type AxisResultProps = {
  rows: AxisCheckRows;
  currentModelId: string | undefined;
};

function AxisResult({ rows, currentModelId }: AxisResultProps) {
  const { latest, previous } = rows;
  const lines = resultLines(latest, previous, currentModelId);

  return (
    <Fragment>
      <dt className="text-muted-foreground">{AXIS_LABELS[rows.axis]}</dt>
      <dd className="flex min-w-0 flex-col gap-0.5 wrap-anywhere">
        <span className={cn("break-keep", lines.isFailure ? "text-destructive-text" : "text-foreground")}>{lines.main}</span>
        {lines.details.map((detail) => (
          <span key={detail} className="break-keep text-xs text-muted-foreground">
            {detail}
          </span>
        ))}
      </dd>
    </Fragment>
  );
}

/** 한 축의 결과 글자. 일시 오류는 결론이 아니라, 런타임이 쓰는 이전 결과(뒤 행)가 있으면 그것을 함께 보인다. 최신이 옛 키로 한 확인이고
 * 지금 키의 이전 결과가 있으면(예전 키로 되돌린 경우) 그것도 보인다. */
function resultLines(
  latest: AdminLlmCredentialCheckItem,
  previous: AdminLlmCredentialCheckItem | undefined,
  currentModelId: string | undefined,
): { main: string; isFailure: boolean; details: string[] } {
  const details = [latest.sentModelId];
  if (latest.errorKind === "unavailable") {
    if (previous === undefined) {
      return { main: TRANSIENT_WITHOUT_PREVIOUS_TEXT, isFailure: false, details: [...details, TRANSIENT_RETRY_HINT_TEXT] };
    }
    return {
      main: TRANSIENT_WITH_PREVIOUS_TEXT,
      isFailure: false,
      details: [...details, `이전: ${checkVerdictText(previous)} · ${formatMonthDayTime(previous.checkedAt)}`],
    };
  }
  if (!latest.isCurrentSecret && previous !== undefined) {
    details.push(`지금 키의 이전 결과: ${checkVerdictText(previous)} · ${formatMonthDayTime(previous.checkedAt)}`);
  }
  if (latest.passed && !latest.isCurrentModelId) details.push(modelIdChangedText(latest.sentModelId, currentModelId));
  return { main: checkVerdictText(latest), isFailure: !latest.passed, details };
}

/** 블록 전체에 붙는 덧붙임. 한 회차는 네 축을 함께 쓰므로 최신 회차 하나로 본다. */
function checkNotes(credential: AdminLlmCredential, latest: AdminLlmCredentialCheckItem): string[] {
  const notes: string[] = [];
  if (!latest.isCurrentSecret) notes.push(OLD_SECRET_CHECK_TEXT);
  // 켜진 항목에는 붙이지 않는다 — 켜는 순간 판이 올라 늘 거짓이다.
  if (credential.state !== "active") {
    if (!latest.isCurrentStateVersion) notes.push(OLD_STATE_CHECK_TEXT);
    const latestRun = credential.checks.filter((check) => check.run === latest.run);
    const isTransientOnly = latestRun.every((check) => check.errorKind === "unavailable");
    // 켜기는 일시 오류를 건너뛰지 않는다 — 런타임과 달리 이전 결과로 내려가지 않는다.
    if (latest.isCurrentSecret && isTransientOnly) notes.push(ENABLE_NEEDS_CONCLUSIVE_TEXT);
  }
  return notes;
}

function lockDescriptionId(credentialId: string, lock: CheckLock): string {
  switch (lock.kind) {
    case "store-missing":
      return STORE_NOTICE_ID;
    case "provider":
      return providerNoteId(credentialId);
    case "open":
    case "checking":
    case "cooldown":
      return checkHintId(credentialId);
    default:
      return assertNever(lock);
  }
}

function checkHint(lock: CheckLock, callCount: number): string {
  switch (lock.kind) {
    case "checking":
      return `모델 ${callCount}개를 차례로 불러요. 응답이 늦으면 몇십 초 걸릴 수 있어요.`;
    case "cooldown":
      // 초를 세는 글자를 두지 않는다 — 스크린리더가 매초 읽는다.
      return "1분에 한 번 — 잠시 뒤 다시 할 수 있어요";
    case "open":
    case "store-missing":
    case "provider":
      return `모델 ${callCount}개에 짧은 요청을 한 번씩 · 합쳐 1센트 미만 · 1분에 한 번`;
    default:
      return assertNever(lock);
  }
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 잠금: ${JSON.stringify(value)}`);
}
