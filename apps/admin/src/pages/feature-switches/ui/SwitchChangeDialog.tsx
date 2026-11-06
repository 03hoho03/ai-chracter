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
import { toast } from "sonner";

import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";
import { RESTING_DISABLED_PRIMARY_CLASS } from "@/shared/ui/restingDisabledPrimaryClass";

import { useSetFeatureSwitchMutation } from "../api/useSetFeatureSwitchMutation";
import { ADJUSTABLE_SWITCH_COPY, onOffText, reflectSentence, WARNING_TEXT } from "../model/switchCopy";
import { effectContextOf, overrideText, resolveEffects } from "../model/switchEffects";
import type { AdminAdjustableSwitch, AdminFeatureSwitchListResponse } from "../model/types";
import { useReasonSave } from "../model/useReasonSave";
import { EffectSections, NoticeLine } from "./EffectSections";
import { ReasonField } from "./ReasonField";
import { SaveFailureAlert } from "./SaveFailureAlert";
import { ValueChange } from "./ValueChange";

type SwitchChangeDialogProps = {
  item: AdminAdjustableSwitch;
  /** 다른 스위치의 지금 값(효과 없음 경고)과 반영 간격을 읽는다. */
  list: AdminFeatureSwitchListResponse;
};

/**
 * 켜기·끄기 확인. 모든 스위치가 같은 틀(전→후, 바뀌는 것, 반영 한 줄, 사유 필수)을 쓴다. 바꿀 값은 지금 실효 값의 반대이고,
 * 서버에 보내는 "화면이 본 덮어쓰기"는 모달을 연 순간의 값이다 — 그새 다른 운영자가 바꿨으면 서버가 409 로 돌려보낸다.
 *
 * 요청 중에는 Esc·바깥 누르기·닫기(X)·취소로 닫지 않는다 — 닫은 뒤 실패하면 그 오류를 보일 자리가 없다.
 */
export const SwitchChangeDialog = createCallable<SwitchChangeDialogProps, void>(({ call, item, list }) => {
  const setMutation = useSetFeatureSwitchMutation();
  const copy = ADJUSTABLE_SWITCH_COPY[item.name];
  const value = !item.effectiveValue;
  const action = value ? "켜기" : "끄기";
  const context = effectContextOf(list, item);
  const effects = resolveEffects(item.name, value, context);
  const expectedOverride = item.override?.value ?? null;

  const { form, submit, failureMessage, isReasonBlank } = useReasonSave({
    save: async (reason) => {
      const result = await setMutation.mutateAsync({ name: item.name, value, reason, expectedOverride });
      toast.success(
        `'${copy.label}' ${onOffText(value)}으로 바꿨어요. 다른 서버는 약 ${context.refreshSeconds}초 안에 따라와요.`,
      );
      for (const warning of result.warnings) toast.warning(WARNING_TEXT[warning](context.refreshSeconds));
      call.end();
    },
    onStale: () => call.end(),
  });
  const {
    register,
    formState: { errors, isSubmitting },
  } = form;
  const isDestructive = effects.tone === "destructive";

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && !isSubmitting && call.end()}>
      <DialogContent className="sm:max-w-lg" onOpenAutoFocus={focusInitialElement}>
        <DialogHeader>
          <DialogTitle>
            {copy.label} {action}
          </DialogTitle>
          <DialogDescription>
            <code className="font-sans wrap-anywhere">{item.name}</code> · 어드민 덮어쓰기로 바꿔요.
          </DialogDescription>
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
              <dt className="text-muted-foreground">실효 값</dt>
              <dd className="font-medium text-foreground">
                <ValueChange before={onOffText(item.effectiveValue)} after={onOffText(value)} />
              </dd>
              <dt className="text-muted-foreground">덮어쓰기</dt>
              <dd className="text-foreground">
                <ValueChange
                  before={
                    item.override === null
                      ? `없음(.env ${onOffText(item.envValue)}을 따름)`
                      : overrideText(item.override.value)
                  }
                  after={onOffText(value)}
                />
              </dd>
              {item.effectiveState !== null && (
                <>
                  <dt className="text-muted-foreground">실제 상태</dt>
                  <dd className="text-foreground">
                    <ValueChange
                      before={item.effectiveState.open ? "열림" : "닫힘"}
                      after={value && item.effectiveState.missingSettings.length === 0 ? "열림" : "닫힘"}
                    />
                  </dd>
                </>
              )}
            </dl>

            <EffectSections effects={effects} />

            {value === item.envValue && (
              // 덮어쓰기가 있을 때만 온다 — 덮어쓰기가 없으면 실효 값이 곧 .env 값이고 바꿀 값은 그 반대다.
              <NoticeLine kind="info">
                .env 값도 {onOffText(value)}이에요 — 덮어쓰기를 지워도 같은 값이 되고, 그쪽은 롤백 때 지울 덮어쓰기를 남기지
                않아요.
              </NoticeLine>
            )}

            <p className="text-sm break-keep text-muted-foreground">{reflectSentence(context.refreshSeconds)}</p>

            <ReasonField id="feature-switch-change-reason" registration={register("reason")} error={errors.reason?.message} />

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
              {isSubmitting ? "저장 중..." : `${copy.label} ${action}`}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
