import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { llmCredentialsQueryOptions } from "../api/llmCredentialsQueryOptions";
import { useSetPoolMutation } from "../api/useSetPoolMutation";
import type { AdminLlmCredential, AdminLlmCredentialListResponse } from "../model/credential";
import type { CredentialFailure } from "../model/failure";
import {
  addedNotice,
  checkedNotice,
  creditBasisNotice,
  deletedNotice,
  droppedByCheck,
  editedNotice,
  poolChangedNotice,
  poolChangePreview,
  reorderedNotice,
  secretReplacedNotice,
  stateChangedNotice,
  type NoticeCopy,
} from "../model/messages";
import {
  candidateShift,
  effectiveRoute,
  latestCheck,
  withoutCredential,
  withRotatedSecret,
  type CandidateChange,
} from "../model/status";
import { AddCredentialDialog } from "./AddCredentialDialog";
import { CheckDroppedNotice, CheckFailureNotice } from "./CheckNotice";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { CreditBasisDialog } from "./CreditBasisDialog";
import { DeleteCredentialDialog } from "./DeleteCredentialDialog";
import { EditCredentialDialog } from "./EditCredentialDialog";
import { checkButtonId, credentialHeadingId } from "./elementIds";
import { focusWhenDialogsClosed } from "./focusWhenDialogsClosed";
import { ReplaceSecretDialog } from "./ReplaceSecretDialog";
import type { CandidateChangeRequest, CredentialScreenSlots, ScreenContext } from "./screenSlots";

type UseCredentialScreenSlotsOptions = {
  /** 지금 화면이 그리는 목록(아직 못 읽었으면 없다). */
  list: AdminLlmCredentialListResponse | undefined;
  /** 서버 스위치 값(아직 못 읽었거나 읽지 못했으면 없다 — 실효 경로를 단정하지 않는다). */
  runtimeSwitch: boolean | undefined;
};

/** 확인 블록에 남기는 확인 호출 뒤의 일. `dropped` 는 그 회차의 결과라 더 새 회차가 오면(다른 탭의 확인 포함) 그리지 않는다. 분당 제한
 * 거절은 잠금이 풀리는 시각에 거둔다 — 남겨 두면 "몇 초 뒤"가 거짓이 된다. */
type CheckNoticeState =
  | { kind: "dropped"; run: number; changes: CandidateChange[] }
  | { kind: "failed"; failure: CredentialFailure; expiresAt: number | undefined };

/**
 * 목록 화면이 언제 부를지 정한 자리(`CredentialScreenSlots`)를 채운다 — 대화상자를 열고, 그 결과를 알림으로 알리고, 확인 블록에 남길
 * 결과를 쥔다. 대화상자의 미리보기는 연 순간 화면의 목록·실효 경로로 계산한다.
 */
export function useCredentialScreenSlots({ list, runtimeSwitch }: UseCredentialScreenSlotsOptions): CredentialScreenSlots {
  const queryClient = useQueryClient();
  const setPoolMutation = useSetPoolMutation();
  const [checkNotices, setCheckNotices] = useState<ReadonlyMap<string, CheckNoticeState>>(new Map());
  useExpireCheckNotices(checkNotices, setCheckNotices);

  const setCheckNotice = (credentialId: string, notice: CheckNoticeState | undefined) => {
    setCheckNotices((prev) => {
      if (notice === undefined && !prev.has(credentialId)) return prev;
      const next = new Map(prev);
      if (notice === undefined) next.delete(credentialId);
      else next.set(credentialId, notice);
      return next;
    });
  };

  /** 키 교체. 바꿨으면 참 — 확인 블록에서 연 경우 다음 할 일(확인 호출)로 포커스를 옮긴다. */
  const replaceSecret = async (credential: AdminLlmCredential, { list: snapshot, route }: ScreenContext) => {
    const changes =
      route.kind === "list"
        ? candidateShift(snapshot.credentials, withRotatedSecret(snapshot.credentials, credential.id))
        : [];
    const outcome = await ReplaceSecretDialog.call({
      credential,
      changes,
      notificationsConfigured: snapshot.notificationsConfigured,
    });
    if (outcome.status !== "replaced") return false;
    // 저장한 키를 읽을 수 없다는 확인 실패는 이 교체로 풀렸을 수 있다 — 다음 확인 호출이 다시 말한다.
    setCheckNotice(credential.id, undefined);
    showNotice(secretReplacedNotice(credential, outcome.credential));
    return true;
  };

  return {
    openAdd: () => {
      void AddCredentialDialog.call({ notificationsConfigured: list?.notificationsConfigured ?? false }).then((outcome) => {
        if (outcome.status !== "added") return;
        // 추가는 목록을 다시 받은 뒤에 끝나므로 캐시에 새 항목이 있다 — 화면에 그려지는 위치로 알린다.
        const current = queryClient.getQueryData(llmCredentialsQueryOptions.queryKey);
        const index = current?.credentials.findIndex((credential) => credential.id === outcome.credential.id) ?? -1;
        showNotice(addedNotice(outcome.credential, index >= 0 ? index + 1 : outcome.credential.position));
        focusWhenDialogsClosed(credentialHeadingId(outcome.credential.id));
      });
    },

    openEdit: (credential) => {
      void EditCredentialDialog.call({ credential }).then((outcome) => {
        if (outcome.status !== "saved") return;
        const isChanged =
          outcome.credential.label !== credential.label || outcome.credential.alertPct !== credential.alertPct;
        showNotice(editedNotice(isChanged));
      });
    },

    openCreditBasis: (credential) => {
      void CreditBasisDialog.call({ credential }).then((outcome) => {
        if (outcome.status === "saved") showNotice(creditBasisNotice(outcome.credential));
      });
    },

    openReplaceSecret: (credential, context) => {
      void replaceSecret(credential, context);
    },

    openDelete: (credential, { list: snapshot, route }) => {
      // 목록이 쓰이는 동안 마지막 항목을 지우면 받을 항목이 없는 것이 아니라 런타임이 env 키로 돈다.
      const isLastOnLiveList = route.kind === "list" && snapshot.credentials.length === 1;
      const changes =
        route.kind === "list" && !isLastOnLiveList
          ? candidateShift(snapshot.credentials, withoutCredential(snapshot.credentials, credential.id))
          : [];
      void DeleteCredentialDialog.call({ credential, changes, isLastOnLiveList }).then((outcome) => {
        if (outcome.status !== "deleted") return;
        setCheckNotice(credential.id, undefined);
        showNotice(deletedNotice(credential));
      });
    },

    openPoolChange: (enabled, { list: snapshot, route }) => {
      const after = effectiveRoute({ ...snapshot, poolEnabled: enabled }, runtimeSwitch);
      const preview = poolChangePreview(enabled, snapshot, route, after);
      const saved: { list?: AdminLlmCredentialListResponse } = {};
      void ConfirmActionDialog.call({
        title: enabled ? "목록 사용 켜기" : "목록 사용 끄기",
        sentences: preview.sentences,
        changes: preview.changes,
        across: preview.across,
        showCacheNote: preview.showCacheNote,
        confirmLabel: enabled ? "목록 사용 켜기" : "목록 사용 끄기",
        pendingLabel: enabled ? "켜는 중…" : "끄는 중…",
        tone: enabled ? "default" : "destructive",
        run: async () => {
          saved.list = await setPoolMutation.mutateAsync({ enabled });
        },
        failureContext: { notificationsConfigured: snapshot.notificationsConfigured },
      }).then((outcome) => {
        if (outcome.status !== "done" || saved.list === undefined) return;
        showNotice(poolChangedNotice(enabled, effectiveRoute(saved.list, runtimeSwitch)));
      });
    },

    confirmCandidateChange: (request) => {
      const losesAxis = request.changes.some((change) => change.to === undefined);
      return ConfirmActionDialog.call({
        ...candidateChangeCopy(request, losesAxis),
        changes: request.changes,
        showCacheNote: true,
        tone: request.action === "disable" || losesAxis ? "destructive" : "default",
        run: request.run,
        failureContext: {
          credentialState: request.credential.state,
          notificationsConfigured: list?.notificationsConfigured,
        },
      });
    },

    notify: (event) => {
      switch (event.kind) {
        case "reordered":
          showNotice(reorderedNotice(event.list));
          return;
        case "state-changed":
          showNotice(stateChangedNotice(event.credential, event.stateBefore));
          return;
        case "checked": {
          const checked = event.response.credential;
          const dropped = droppedByCheck(event.before, checked, effectiveRoute(event.before, runtimeSwitch));
          const latest = latestCheck(checked.checks);
          setCheckNotice(
            checked.id,
            dropped.length > 0 && latest !== undefined ? { kind: "dropped", run: latest.run, changes: dropped } : undefined,
          );
          showNotice(checkedNotice(event.response));
          return;
        }
        case "failed":
          // 확인 호출의 실패는 그 항목의 확인 블록에 남긴다(다음 할 일이 그 자리에 있다). 지워진 항목은 그릴 블록이 없어 알림으로.
          if (event.action === "check" && event.failure.kind !== "not-found") {
            const expiresAt =
              event.failure.kind === "rate-limited" ? Date.now() + event.failure.retryAfterSeconds * 1000 : undefined;
            setCheckNotice(event.credential.id, { kind: "failed", failure: event.failure, expiresAt });
            return;
          }
          toast.error(event.failure.message);
          return;
        default:
          assertNever(event);
      }
    },

    renderCheckNotice: (credential) => {
      const notice = checkNotices.get(credential.id);
      if (notice === undefined) return null;
      if (notice.kind === "dropped") {
        return latestCheck(credential.checks)?.run === notice.run ? <CheckDroppedNotice changes={notice.changes} /> : null;
      }
      const index = list?.credentials.findIndex((entry) => entry.id === credential.id) ?? -1;
      if (list === undefined || index < 0) return null;
      const context: ScreenContext = { list, route: effectiveRoute(list, runtimeSwitch) };
      const repaste = async () => {
        if (await replaceSecret(credential, context)) focusWhenDialogsClosed(checkButtonId(credential.id));
      };
      return (
        <CheckFailureNotice
          message={notice.failure.message}
          itemName={`${index + 1}번째 ${credential.label}`}
          onRepasteSecret={notice.failure.kind === "secret-unreadable" ? () => void repaste() : undefined}
        />
      );
    },
  };
}

/** 분당 제한 거절 안내를 잠금이 풀리는 순간 거둔다 — 타이머라는 외부 시스템에 맞추는 동기화다. */
function useExpireCheckNotices(
  notices: ReadonlyMap<string, CheckNoticeState>,
  setNotices: (update: (prev: ReadonlyMap<string, CheckNoticeState>) => ReadonlyMap<string, CheckNoticeState>) => void,
) {
  useEffect(() => {
    const expiries = [...notices.values()].flatMap((notice) =>
      notice.kind === "failed" && notice.expiresAt !== undefined ? [notice.expiresAt] : [],
    );
    if (expiries.length === 0) return;
    const timer = window.setTimeout(
      () => {
        const now = Date.now();
        setNotices((prev) => new Map([...prev].filter(([, notice]) => !isExpired(notice, now))));
      },
      Math.max(0, Math.min(...expiries) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [notices, setNotices]);
}

function isExpired(notice: CheckNoticeState, now: number): boolean {
  return notice.kind === "failed" && notice.expiresAt !== undefined && notice.expiresAt <= now;
}

/** 첫 후보가 바뀌는 순서·켜기·끄기 확인의 글자. 켜기는 그 항목이 받게 되는 축만, 끄기·순서는 다른 항목으로 가는 축이 바뀐다. */
function candidateChangeCopy({ action, credential }: CandidateChangeRequest, losesAxis: boolean) {
  const subject = `‘${credential.label}’`;
  switch (action) {
    case "reorder":
      return {
        title: `${subject} 옮기기`,
        sentences: ["옮기면 다음 호출부터 아래 모델을 받는 항목이 바뀌어요."],
        confirmLabel: "옮기기",
        pendingLabel: "옮기는 중…",
      };
    case "enable": {
      const verb = credential.state === "exhausted" ? "다시 켜기" : "켜기";
      return {
        title: `${subject} ${verb}`,
        sentences: ["켜면 다음 호출부터 아래 모델을 이 항목이 받아요."],
        confirmLabel: verb,
        pendingLabel: "켜는 중…",
      };
    }
    case "disable":
      return {
        title: `${subject} 끄기`,
        sentences: losesAxis
          ? [
              "끄면 다음 호출부터 아래 모델을 받는 항목이 바뀌어요.",
              "받을 항목이 없어지는 모델은 env 키로 넘어가지 않고 실패·환불돼요.",
            ]
          : ["끄면 다음 호출부터 아래 모델을 다른 항목이 받아요."],
        confirmLabel: "끄기",
        pendingLabel: "끄는 중…",
      };
    default:
      return assertNever(action);
  }
}

function showNotice({ title, description }: NoticeCopy) {
  if (description === undefined) toast.success(title);
  else toast.success(title, { description });
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 값: ${JSON.stringify(value)}`);
}
