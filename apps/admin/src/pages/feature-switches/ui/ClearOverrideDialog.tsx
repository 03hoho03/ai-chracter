import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef } from "react";
import { toast } from "sonner";

import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";
import { RESTING_DISABLED_PRIMARY_CLASS } from "@/shared/ui/restingDisabledPrimaryClass";

import { useClearFeatureSwitchOverrideMutation } from "../api/useClearFeatureSwitchOverrideMutation";
import {
  ADJUSTABLE_SWITCH_COPY,
  onOffText,
  reflectSentence,
  SWITCH_GROUPS_IN_ORDER,
  switchLabelOf,
  WARNING_TEXT,
} from "../model/switchCopy";
import { effectContextOf, resolveEffects, type ResolvedEffects } from "../model/switchEffects";
import type { AdminAdjustableSwitch, AdminFeatureSwitchListResponse, AdminUnknownOverride } from "../model/types";
import { useReasonSave } from "../model/useReasonSave";
import { EffectSections } from "./EffectSections";
import { groupHeadingId, toggleButtonId, UNKNOWN_OVERRIDES_HEADING_ID } from "./elementIds";
import { ReasonField } from "./ReasonField";
import { SaveFailureAlert } from "./SaveFailureAlert";
import { ValueChange } from "./ValueChange";

type ClearOverrideDialogProps =
  | { kind: "known"; item: AdminAdjustableSwitch; list: AdminFeatureSwitchListResponse }
  /** 이 화면이 버튼으로 다루지 않는 이름의 덮어쓰기 — 지금은 무시되고 있어 실효 값이 바뀌지 않는다. */
  | { kind: "unknown"; override: AdminUnknownOverride; refreshSeconds: number };

/**
 * 덮어쓰기 지우기 확인. 지워서 실효 값이 바뀌면(덮어쓰기와 `.env` 값이 다르면) 그 방향의 바꾸기와 같은 결과 문장·확정 톤을
 * 싣는다 — 노벨 공개 정책을 켠 덮어쓰기를 지우면 곧 정책 끄기다.
 *
 * 저장되거나 낡은 값으로 닫히면 포커스를 직접 옮긴다. 지우면 이 모달을 연 `덮어쓰기 지우기…` 버튼이 사라져, 그대로 두면
 * 포커스가 화면 맨 위로 가 긴 스위치 목록에서 자리를 잃는다. 이름을 아는 스위치는 같은 행의 켜기·끄기 버튼으로, 모르는 이름은 그
 * 섹션 제목(행이 다 지워져 섹션이 사라졌으면 첫 묶음 제목)으로 보낸다. 취소면 연 버튼이 그대로라 기본 복원에 맡긴다.
 */
export const ClearOverrideDialog = createCallable<ClearOverrideDialogProps, void>((props) => {
  const { call } = props;
  const clearMutation = useClearFeatureSwitchOverrideMutation();
  const shouldMoveFocusRef = useRef(false);
  const view = clearView(props);

  const { form, submit, failureMessage, isReasonBlank } = useReasonSave({
    save: async (reason) => {
      const result = await clearMutation.mutateAsync({ name: view.name, reason, expectedOverride: view.overrideValue });
      toast.success(view.doneMessage);
      for (const warning of result.warnings) toast.warning(WARNING_TEXT[warning](view.refreshSeconds));
      shouldMoveFocusRef.current = true;
      call.end();
    },
    onStale: () => {
      shouldMoveFocusRef.current = true;
      call.end();
    },
  });
  const {
    register,
    formState: { errors, isSubmitting },
  } = form;
  const isDestructive = view.effects?.tone === "destructive";

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && !isSubmitting && call.end()}>
      <DialogContent
        className="sm:max-w-lg"
        onOpenAutoFocus={focusInitialElement}
        onCloseAutoFocus={(event) => {
          if (!shouldMoveFocusRef.current) return;
          event.preventDefault();
          focusAfterClear(props);
        }}
      >
        <DialogHeader>
          <DialogTitle>{view.title}</DialogTitle>
          <DialogDescription>{view.description}</DialogDescription>
        </DialogHeader>

        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void submit(event);
          }}
          className="flex min-h-0 flex-1 flex-col gap-4"
        >
          <DialogBody className="relative flex flex-col gap-4">
            <dl className="grid shrink-0 grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 rounded-lg border border-border p-3 text-sm">
              {view.effective !== null && (
                <>
                  <dt className="text-muted-foreground">실효 값</dt>
                  <dd className="font-medium text-foreground">
                    {view.effective.before === view.effective.after ? (
                      `그대로 ${view.effective.after}`
                    ) : (
                      <ValueChange before={view.effective.before} after={view.effective.after} />
                    )}
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">덮어쓰기</dt>
              <dd className="text-foreground">
                <ValueChange before={onOffText(view.overrideValue)} after="없음" />
              </dd>
              {view.state !== null && (
                <>
                  <dt className="text-muted-foreground">실제 상태</dt>
                  <dd className="text-foreground">
                    <ValueChange before={view.state.before} after={view.state.after} />
                  </dd>
                </>
              )}
            </dl>

            {view.effects === null ? (
              view.kind === "known" && (
                <p className="text-sm break-keep text-foreground">
                  실효 값은 그대로예요 — 이력이 남고, 롤백 때 옮겨 적을 덮어쓰기가 하나 줄어요.
                </p>
              )
            ) : (
              <EffectSections effects={view.effects} />
            )}

            {view.kind === "known" && (
              <p className="text-sm break-keep text-muted-foreground">{reflectSentence(view.refreshSeconds)}</p>
            )}

            <ReasonField id="feature-switch-clear-reason" registration={register("reason")} error={errors.reason?.message} />

            {failureMessage !== null && <SaveFailureAlert message={failureMessage} />}
          </DialogBody>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              autoFocus
              data-initial-focus
              disabled={isSubmitting}
              onClick={() => call.end()}
            >
              취소
            </Button>
            <Button
              type="submit"
              variant={isDestructive ? "destructive" : "default"}
              // 사유를 적기 전까지 오래 머무는 비활성이라 핑크 덩어리로 남지 않게 무채색으로 둔다(요청 중의 잠금은 그대로).
              className={cn(!isDestructive && isReasonBlank && RESTING_DISABLED_PRIMARY_CLASS)}
              disabled={isReasonBlank || isSubmitting}
            >
              {isSubmitting ? "저장 중..." : "덮어쓰기 지우기"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});

type ClearView = {
  kind: ClearOverrideDialogProps["kind"];
  name: string;
  overrideValue: boolean;
  title: string;
  description: string;
  doneMessage: string;
  /** 모르는 이름은 실효 값이 없다(이 판이 그 스위치를 읽지 않는다). */
  effective: { before: string; after: string } | null;
  state: { before: string; after: string } | null;
  /** 실효 값이 바뀔 때만 그 방향의 결과 문장. */
  effects: ResolvedEffects | null;
  refreshSeconds: number;
};

function clearView(props: ClearOverrideDialogProps): ClearView {
  if (props.kind === "unknown") {
    const { override } = props;
    const label = switchLabelOf(override.name);
    return {
      kind: "unknown",
      name: override.name,
      overrideValue: override.value,
      title: "모르는 덮어쓰기 지우기",
      description: `${override.name} — 지금 이미지가 다루지 않는 이름이라 지금은 무시되고 있어요. 지우면 이 이름을 다루던 판으로 되돌려도 되살아나지 않아요.`,
      doneMessage: `'${label ?? override.name}' 덮어쓰기를 지웠어요.`,
      effective: null,
      state: null,
      effects: null,
      refreshSeconds: props.refreshSeconds,
    };
  }

  const { item, list } = props;
  const copy = ADJUSTABLE_SWITCH_COPY[item.name];
  const overrideValue = item.override?.value ?? item.effectiveValue;
  const after = item.envValue;
  const isChanging = overrideValue !== after;
  const missing = item.effectiveState?.missingSettings ?? [];
  return {
    kind: "known",
    name: item.name,
    overrideValue,
    title: `${copy.label} 덮어쓰기 지우기`,
    description: `덮어쓰기를 지우면 이 서버가 기동 때 읽은 .env 값 ${onOffText(after)}으로 돌아가요. .env 파일을 고쳤다면 교체로 반영한 뒤에 지우세요.`,
    doneMessage: `'${copy.label}' 덮어쓰기를 지웠어요 — .env 값 ${onOffText(after)}으로 돌아가요.`,
    effective: { before: onOffText(item.effectiveValue), after: onOffText(after) },
    state:
      item.effectiveState === null
        ? null
        : { before: item.effectiveState.open ? "열림" : "닫힘", after: after && missing.length === 0 ? "열림" : "닫힘" },
    effects: isChanging ? resolveEffects(item.name, after, effectContextOf(list, item)) : null,
    refreshSeconds: list.refreshIntervalSeconds,
  };
}

function focusAfterClear(props: ClearOverrideDialogProps) {
  if (props.kind === "known") {
    document.getElementById(toggleButtonId(props.item.name))?.focus();
    return;
  }
  const firstGroup = SWITCH_GROUPS_IN_ORDER[0];
  const target =
    document.getElementById(UNKNOWN_OVERRIDES_HEADING_ID) ??
    (firstGroup === undefined ? null : document.getElementById(groupHeadingId(firstGroup)));
  target?.focus();
}
