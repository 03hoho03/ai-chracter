import { Button } from "@ai-character-chat/ui/components/button";
import { useEffect, useState } from "react";

import { useCheckCredentialMutation } from "../api/useCheckCredentialMutation";
import { useCredentialStateMutation, type CredentialStateAction } from "../api/useCredentialStateMutation";
import { useReorderCredentialsMutation } from "../api/useReorderCredentialsMutation";
import { CHECK_COOLDOWN_SECONDS } from "../model/checkCall";
import type { AdminLlmCredential, AdminLlmCredentialListResponse } from "../model/credential";
import { classifyCredentialFailure } from "../model/failure";
import { EMPTY_LIST_TEXT } from "../model/labels";
import {
  candidateShift,
  describeCredentialStatus,
  moveCredential,
  withCredentialState,
  type EffectiveRoute,
  type FirstCandidates,
  type MoveDirection,
} from "../model/status";
import { AddCredentialButton } from "./AddCredentialButton";
import type { CheckLock } from "./CheckResults";
import { CredentialItem } from "./CredentialItem";
import { moveButtonId, ORDER_HEADING_ID } from "./elementIds";
import type { CredentialScreenSlots } from "./screenSlots";

type CredentialListProps = {
  list: AdminLlmCredentialListResponse;
  route: EffectiveRoute;
  firsts: FirstCandidates;
  /** 자격 목록을 다시 받는 중(자기 추가·삭제 뒤의 재조회 포함). 그동안 위·아래를 잠근다. */
  isListFetching: boolean;
  slots: CredentialScreenSlots;
};

/** 대화상자가 닫히는 동안(닫힘 전환 포함) 포커스 이동을 미루는 최대 프레임 수. 넘기면 그냥 옮긴다. */
const MAX_FOCUS_WAIT_FRAMES = 120;

/**
 * 순서 절. 위·아래는 누를 때마다 저장하고, 실효 경로가 목록인 동안 첫 후보가 바뀌는 이동·켜기·끄기만 확인받는다 — 바뀌지 않는
 * 동작에 매번 확인을 띄우면 경고가 무뎌진다. 낙관 갱신은 없다: 판·지문·허용 목록 같은 서버 조건이 결과를 정하고 거절이 흔하다.
 */
export function CredentialList({ list, route, firsts, isListFetching, slots }: CredentialListProps) {
  const reorderMutation = useReorderCredentialsMutation();
  const stateMutation = useCredentialStateMutation();
  const checkMutation = useCheckCredentialMutation();
  const [staleNotice, setStaleNotice] = useState<string | null>(null);
  const [statePendingIds, setStatePendingIds] = useState<ReadonlySet<string>>(new Set());
  const [checkingIds, setCheckingIds] = useState<ReadonlySet<string>>(new Set());
  const [checkCooldowns, setCheckCooldowns] = useState<ReadonlyMap<string, number>>(new Map());
  useExpireCooldowns(checkCooldowns, setCheckCooldowns);

  const { credentials } = list;
  const isOrderLocked = reorderMutation.isPending || isListFetching;
  const context = { list, route };

  const handleMove = async (index: number, direction: MoveDirection) => {
    // 판 번호와 새 순서를 누른 순간의 같은 목록에서 만든다 — 확인 대화상자가 열린 동안 창 포커스 재조회가 목록을 바꿔도 두 값은
    // 이때의 것이라, 새 판에 옛 순서를(또는 옛 판에 새 순서를) 섞어 보내지 않는다.
    const snapshot = list;
    const moved = snapshot.credentials[index];
    if (moved === undefined) return;
    const reordered = moveCredential(snapshot.credentials, index, direction);
    const request = { baseListRevision: snapshot.listRevision, ids: reordered.map((credential) => credential.id) };
    const saved: { list?: AdminLlmCredentialListResponse } = {};
    const run = async () => {
      saved.list = await reorderMutation.mutateAsync(request);
    };
    const changes = candidateShift(snapshot.credentials, reordered);

    try {
      if (route.kind === "list" && changes.length > 0) {
        const outcome = await slots.confirmCandidateChange({ action: "reorder", credential: moved, changes, run });
        if (outcome.status === "stale") setStaleNotice(outcome.message);
        if (outcome.status !== "done") return;
      } else {
        await run();
      }
    } catch (error) {
      const failure = classifyCredentialFailure(error);
      if (failure.kind === "stale-order") setStaleNotice(failure.message);
      else slots.notify({ kind: "failed", action: "reorder", credential: moved, failure });
      return;
    }
    if (saved.list === undefined) return;
    setStaleNotice(null);
    focusWhenSettled(moved.id, saved.list.credentials, direction);
    slots.notify({ kind: "reordered", list: saved.list });
  };

  const handleToggleState = async (credential: AdminLlmCredential) => {
    const action: CredentialStateAction = credential.state === "active" ? "disable" : "enable";
    const after = withCredentialState(credentials, credential.id, action === "enable" ? "active" : "disabled");
    const changes = candidateShift(credentials, after);
    const saved: { credential?: AdminLlmCredential } = {};
    const run = async () => {
      setStatePendingIds((prev) => new Set(prev).add(credential.id));
      try {
        saved.credential = await stateMutation.mutateAsync({ id: credential.id, action });
      } finally {
        setStatePendingIds((prev) => withoutKey(prev, credential.id));
      }
    };

    try {
      if (route.kind === "list" && changes.length > 0) {
        const outcome = await slots.confirmCandidateChange({ action, credential, changes, run });
        if (outcome.status !== "done") return;
      } else {
        await run();
      }
    } catch (error) {
      const failure = classifyCredentialFailure(error, {
        credentialState: credential.state,
        notificationsConfigured: list.notificationsConfigured,
      });
      slots.notify({ kind: "failed", action, credential, failure });
      return;
    }
    if (saved.credential !== undefined) {
      slots.notify({ kind: "state-changed", action, credential: saved.credential, stateBefore: credential.state });
    }
  };

  const handleCheck = async (credential: AdminLlmCredential) => {
    const before = list;
    setCheckingIds((prev) => new Set(prev).add(credential.id));
    try {
      const response = await checkMutation.mutateAsync(credential.id);
      startCooldown(credential.id, CHECK_COOLDOWN_SECONDS);
      slots.notify({ kind: "checked", before, response });
    } catch (error) {
      const failure = classifyCredentialFailure(error);
      // 서버는 항목을 찾기 전에 횟수를 세므로 서버에 닿은 실패만 1분 창을 쓴다(결과 미확정은 닿았을 수 있어 센다). 보내기 직전에
      // 오프라인이었던 실패는 서버에 닿지 않아 횟수가 없으니 잠그지 않는다.
      if (failure.kind !== "offline") {
        const seconds = failure.kind === "rate-limited" ? failure.retryAfterSeconds : CHECK_COOLDOWN_SECONDS;
        startCooldown(credential.id, seconds);
      }
      slots.notify({ kind: "failed", action: "check", credential, failure });
    } finally {
      setCheckingIds((prev) => withoutKey(prev, credential.id));
    }
  };

  const startCooldown = (credentialId: string, seconds: number) => {
    setCheckCooldowns((prev) => new Map(prev).set(credentialId, Date.now() + seconds * 1000));
  };

  const checkLockOf = (credential: AdminLlmCredential): CheckLock => {
    if (credential.provider !== "anthropic") return { kind: "provider" };
    if (!list.storeConfigured) return { kind: "store-missing" };
    if (checkingIds.has(credential.id)) return { kind: "checking" };
    if (checkCooldowns.has(credential.id)) return { kind: "cooldown" };
    return { kind: "open" };
  };

  return (
    <section aria-labelledby={ORDER_HEADING_ID} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id={ORDER_HEADING_ID} className="text-lg font-semibold text-foreground">
          순서
        </h2>
        <p className="break-keep text-sm text-muted-foreground">
          위에 있을수록 먼저 받아요. 위·아래 버튼을 누를 때마다 바로 저장해요.
        </p>
      </div>

      {staleNotice !== null && (
        <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border border-border p-3">
          <p className="break-keep text-sm text-foreground">{staleNotice}</p>
          <Button type="button" variant="outline" size="sm" onClick={() => setStaleNotice(null)}>
            닫기
          </Button>
        </div>
      )}

      {credentials.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-border px-4 py-8 sm:px-6">
          <p className="break-keep text-sm text-muted-foreground">{EMPTY_LIST_TEXT}</p>
          <AddCredentialButton variant="outline" isBlocked={!list.storeConfigured} onAdd={slots.openAdd} />
        </div>
      ) : (
        // Tailwind 기본 스타일이 목록 표식을 지우면 Safari(VoiceOver)가 목록의 뜻을 버려 role 로 되살린다.
        <ol role="list" aria-label="Claude 자격 순서" className="flex flex-col gap-3">
          {credentials.map((credential, index) => (
            <CredentialItem
              key={credential.id}
              credential={credential}
              position={index + 1}
              total={credentials.length}
              status={describeCredentialStatus(credential, firsts, route)}
              modelIds={list.modelIds}
              isStoreMissing={!list.storeConfigured}
              isOrderLocked={isOrderLocked}
              isStatePending={statePendingIds.has(credential.id)}
              checkLock={checkLockOf(credential)}
              checkNotice={slots.renderCheckNotice(credential)}
              onMove={(direction) => void handleMove(index, direction)}
              onToggleState={() => void handleToggleState(credential)}
              onCheck={() => void handleCheck(credential)}
              onEdit={() => slots.openEdit(credential)}
              onCreditBasis={() => slots.openCreditBasis(credential)}
              onReplaceSecret={() => slots.openReplaceSecret(credential, context)}
              onDelete={() => slots.openDelete(credential, context)}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

/** 확인 호출 잠금이 끝나는 순간 그 항목을 지운다 — 타이머라는 외부 시스템에 맞추는 동기화다. */
function useExpireCooldowns(
  cooldowns: ReadonlyMap<string, number>,
  setCooldowns: (update: (prev: ReadonlyMap<string, number>) => ReadonlyMap<string, number>) => void,
) {
  useEffect(() => {
    if (cooldowns.size === 0) return;
    const nextExpiry = Math.min(...cooldowns.values());
    const timer = window.setTimeout(
      () => {
        const now = Date.now();
        setCooldowns((prev) => new Map([...prev].filter(([, until]) => until > now)));
      },
      Math.max(0, nextExpiry - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [cooldowns, setCooldowns]);
}

function withoutKey(set: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(set);
  next.delete(key);
  return next;
}

/** 옮긴 항목의 같은 방향 버튼. 끝에 닿아 그 버튼이 비활성이면 같은 항목의 반대 방향 버튼이다 — 맨 위로 올린 항목은 "한 칸 아래로". */
function movedButtonTarget(index: number, total: number, id: string, direction: MoveDirection): string {
  const isAtEdge = direction === "up" ? index === 0 : index === total - 1;
  const opposite: MoveDirection = direction === "up" ? "down" : "up";
  return moveButtonId(id, isAtEdge ? opposite : direction);
}

/**
 * 순서를 저장한 뒤 포커스를 옮긴 항목의 버튼으로 되돌린다. 항목을 `id` 로 그려 React 가 `li` 를 옮기는데, DOM 에서 옮겨진 요소는
 * 포커스를 잃는다. 새 순서가 화면에 그려진 뒤(그 `li` 가 새 자리에 선 뒤), 확인 대화상자를 거쳤다면 그것이 닫힌 뒤에 옮긴다 — 열린
 * 대화상자의 포커스 가두기가 밖으로 나간 포커스를 되돌리기 때문이다. 대화상자 래퍼는 포커스를 잃었을 때만 연 버튼으로 돌려주므로 이
 * 이동과 다투지 않는다.
 */
function focusWhenSettled(id: string, savedOrder: readonly AdminLlmCredential[], direction: MoveDirection) {
  const index = savedOrder.findIndex((credential) => credential.id === id);
  if (index < 0) return;
  const targetId = movedButtonTarget(index, savedOrder.length, id, direction);
  let frames = 0;
  const tick = () => {
    frames += 1;
    const target = document.getElementById(targetId);
    const item = target?.closest("li") ?? null;
    const isInPlace = item !== null && item.parentElement?.children[index] === item;
    const isOverlayOpen = document.querySelector('[role="dialog"], [role="alertdialog"]') !== null;
    if ((!isInPlace || isOverlayOpen) && frames < MAX_FOCUS_WAIT_FRAMES) {
      requestAnimationFrame(tick);
      return;
    }
    target?.focus();
  };
  requestAnimationFrame(tick);
}
