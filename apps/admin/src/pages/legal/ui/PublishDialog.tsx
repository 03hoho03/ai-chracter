import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { ActionChoice } from "@/shared/ui/ActionChoice";
import { RESTING_DISABLED_PRIMARY_CLASS } from "@/shared/ui/restingDisabledPrimaryClass";

import {
  ADVERSE_CHANGE_NOTICE_DAYS,
  daysBetween,
  isKstDateString,
  kstMidnightIso,
  nextKstDate,
  todayKst,
  type KstDateString,
} from "../model/effectiveDate";
import {
  CONSENT_UNIT_LABELS,
  isLegalConsentUnit,
  LEGAL_KIND_LABELS,
  reconsentScopesOf,
  type LegalConsentUnit,
  type LegalKind,
} from "../model/legalKind";
import { type AdminLegalPublishRequest, usePublishMutation } from "../api/usePublishMutation";

// 서버(`AdminLegalPublishRequest.version`)와 같은 형식 제약 — 날짜, 같은 날 다시 게시하면 `.2` 부터의 순번. 422 를 받고서야
// 알리는 대신 여기서 미리 막는다.
const VERSION_PATTERN = /^\d{4}-\d{2}-\d{2}(\.([2-9]|[1-9]\d+))?$/;

const EFFECTIVE_MODE_OPTIONS = [
  { value: "immediate", label: "즉시 — 게시하는 순간 현행판이 돼요" },
  { value: "scheduled", label: "날짜 지정 — 그날 0시(한국 시각)에 시행돼요" },
] as const;

type EffectiveMode = (typeof EFFECTIVE_MODE_OPTIONS)[number]["value"];

/** 오늘 날짜를 받아 만든다 — 시행일은 내일 이후여야 한다(오늘 0시는 이미 지난 시각이라 서버가 422 로 거부한다). */
function buildPublishSchema(today: KstDateString) {
  return z
    .object({
      version: z
        .string()
        .trim()
        .regex(VERSION_PATTERN, "YYYY-MM-DD 형식으로, 같은 날 두 번째 판부터는 YYYY-MM-DD.2 처럼 입력해 주세요."),
      effectiveMode: z.enum(["immediate", "scheduled"]),
      effectiveDate: z.string(),
      reconsentScopes: z.array(z.custom<LegalConsentUnit>(isLegalConsentUnit)),
    })
    .superRefine((values, ctx) => {
      if (values.effectiveMode !== "scheduled") return;
      if (!isKstDateString(values.effectiveDate)) {
        ctx.addIssue({ code: "custom", path: ["effectiveDate"], message: "시행일을 골라 주세요." });
      } else if (values.effectiveDate <= today) {
        ctx.addIssue({
          code: "custom",
          path: ["effectiveDate"],
          message: "시행일은 내일 이후여야 해요. 오늘 시행하려면 '즉시'를 고르세요.",
        });
      }
    });
}

type PublishFormValues = z.infer<ReturnType<typeof buildPublishSchema>>;

function toPublishRequest(values: PublishFormValues): AdminLegalPublishRequest {
  const request: AdminLegalPublishRequest = { version: values.version, reconsentScopes: values.reconsentScopes };
  // "즉시"는 칸을 보내지 않는다 — 서버가 게시 시각을 시행 시각으로 넣는다. 화면 시계로 지금을 보내면 서버 시계보다 조금
  // 이르게 도착해 "게시 시각보다 이른 시행 시각"으로 거부될 수 있다.
  if (values.effectiveMode === "scheduled" && isKstDateString(values.effectiveDate)) {
    request.effectiveAt = kstMidnightIso(values.effectiveDate);
  }
  return request;
}

type PublishDialogProps = {
  kind: LegalKind;
  /** 저장된 초안에 (공백이 아닌) 변경 안내가 있는지. 게시는 화면이 아니라 저장된 초안을 발행한다. */
  hasSavedNotice: boolean;
};

/** 게시했으면 `true` 로 끝난다 — 연 쪽이 그 문서의 편집 버퍼를 비우는 데 쓴다(서버가 게시와 함께 초안 안내를 비우므로).
 *
 * 입력 실패는 조용히 삼키지 않고 폼을 닫지 않는다. 서버가 문장으로 거절한 경우(409 버전 중복·시행 예정 판 있음, 422 안내
 * 없음·시행 시각 지남)는 그 문장을 폼 위에 그대로 보여 준다 — 어느 칸을 고쳐야 하는지가 문장에 들어 있다. 그 밖의 실패는
 * 토스트다. */
export const PublishDialog = createCallable<PublishDialogProps, boolean>(({ call, kind, hasSavedNotice }) => {
  const id = useId();
  const publishMutation = usePublishMutation(kind);
  // 대화상자를 연 날을 기준으로 고정한다 — 기본 버전·시행일 하한·30일 경고가 한 기준을 쓴다.
  const [today] = useState(todayKst);
  const scopeOptions = reconsentScopesOf(kind);
  const {
    control,
    register,
    handleSubmit,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<PublishFormValues>({
    resolver: zodResolver(buildPublishSchema(today)),
    defaultValues: { version: today, effectiveMode: "immediate", effectiveDate: "", reconsentScopes: [] },
  });
  const [effectiveMode, effectiveDate, reconsentScopes] = useWatch({
    control,
    name: ["effectiveMode", "effectiveDate", "reconsentScopes"],
  });

  const hasScopes = reconsentScopes.length > 0;
  const isBlockedByMissingNotice = hasScopes && !hasSavedNotice;
  const isScheduled = effectiveMode === "scheduled";
  // 즉시 시행은 공지 기간이 0일이다. 날짜를 아직 고르지 않았거나 고를 수 없는 날(오늘 이전)이면 경고하지 않는다(입력 오류가
  // 먼저 보인다).
  let daysUntilEffective: number | undefined;
  if (!isScheduled) daysUntilEffective = 0;
  else if (isKstDateString(effectiveDate) && effectiveDate > today) {
    daysUntilEffective = daysBetween(today, effectiveDate);
  }
  const isShortNotice =
    hasScopes && daysUntilEffective !== undefined && daysUntilEffective < ADVERSE_CHANGE_NOTICE_DAYS;

  let submitLabel = isScheduled ? "예약 게시" : "게시";
  if (isSubmitting) submitLabel = "게시 중...";

  const versionErrorId = `${id}-version-error`;
  const dateErrorId = `${id}-date-error`;

  const onSubmit = async (values: PublishFormValues) => {
    try {
      await publishMutation.mutateAsync(toPublishRequest(values));
      toast.success(
        values.effectiveMode === "scheduled"
          ? `${LEGAL_KIND_LABELS[kind]} v${values.version}을 ${values.effectiveDate} 시행으로 예약했어요.`
          : `${LEGAL_KIND_LABELS[kind]} v${values.version}을 게시했어요.`,
      );
      call.end(true);
    } catch (error) {
      if (isApiError(error) && (error.status === 409 || error.status === 422) && typeof error.detail === "string") {
        setError("root.server", { message: error.detail });
      } else {
        toast.error("게시에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(false)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{LEGAL_KIND_LABELS[kind]} 게시</DialogTitle>
          <DialogDescription className="break-keep">
            저장된 초안을 새 판으로 게시해요. 초안 본문은 남고, 초안의 변경 안내는 이 판으로 옮겨진 뒤 비워져요.
          </DialogDescription>
        </DialogHeader>

        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            clearErrors("root.server");
            void handleSubmit(onSubmit)(event);
          }}
          className="flex min-h-0 flex-1 flex-col gap-4"
        >
          <DialogBody className="flex flex-col gap-5">
            {errors.root?.server && (
              <p
                role="alert"
                className="rounded-lg bg-destructive/10 p-3 text-sm break-keep wrap-break-word text-destructive-text"
              >
                {errors.root.server.message}
              </p>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-version`}>버전</Label>
              <Input
                id={`${id}-version`}
                placeholder="예: 2026-09-06"
                aria-invalid={!!errors.version}
                aria-describedby={errors.version ? versionErrorId : `${id}-version-hint`}
                {...register("version")}
              />
              {errors.version ? (
                <p id={versionErrorId} role="alert" className="text-xs break-keep text-destructive-text">
                  {errors.version.message}
                </p>
              ) : (
                <p id={`${id}-version-hint`} className="text-xs break-keep text-muted-foreground">
                  기본값은 오늘(한국 날짜)이에요. 같은 날 두 번째 판은 끝에 .2 를 붙여요.
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <Controller
                name="effectiveMode"
                control={control}
                render={({ field }) => (
                  <ActionChoice<EffectiveMode>
                    legend="시행 시각"
                    options={EFFECTIVE_MODE_OPTIONS}
                    value={field.value}
                    onValueChange={field.onChange}
                  />
                )}
              />
              {isScheduled && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`${id}-date`}>시행일 (한국 시각 0시)</Label>
                  <Input
                    id={`${id}-date`}
                    type="date"
                    min={nextKstDate(today)}
                    aria-invalid={!!errors.effectiveDate}
                    aria-describedby={errors.effectiveDate ? dateErrorId : undefined}
                    {...register("effectiveDate")}
                  />
                  {errors.effectiveDate && (
                    <p id={dateErrorId} role="alert" className="text-xs break-keep text-destructive-text">
                      {errors.effectiveDate.message}
                    </p>
                  )}
                  <p className="text-xs break-keep text-muted-foreground">
                    시행일 전까지는 지금 판이 현행이고, 예약한 판은 이력에서 철회할 수 있어요. 예약한 판이 있는 동안은 이
                    문서의 다른 판을 게시할 수 없어요.
                  </p>
                </div>
              )}
            </div>

            {scopeOptions.length > 0 ? (
              <fieldset className="flex flex-col gap-2">
                <legend className="mb-2 text-sm font-medium text-foreground">재동의 범위</legend>
                <Controller
                  name="reconsentScopes"
                  control={control}
                  render={({ field }) => (
                    <>
                      {scopeOptions.map((scope) => {
                        const checkboxId = `${id}-scope-${scope}`;
                        return (
                          <div key={scope} className="flex items-center gap-2">
                            <Checkbox
                              id={checkboxId}
                              checked={field.value.includes(scope)}
                              onCheckedChange={(checked) =>
                                field.onChange(
                                  checked === true
                                    ? scopeOptions.filter((option) => option === scope || field.value.includes(option))
                                    : field.value.filter((value) => value !== scope),
                                )
                              }
                            />
                            <Label htmlFor={checkboxId} className="font-normal">
                              {CONSENT_UNIT_LABELS[scope]} 재동의
                            </Label>
                          </div>
                        );
                      })}
                    </>
                  )}
                />
                <p className="text-xs break-keep text-muted-foreground">
                  고른 동의를 이 판에 아직 하지 않은 회원은 시행일부터 다시 동의해야 서비스를 쓸 수 있어요. 고르지 않으면
                  공개만 해요.
                </p>
              </fieldset>
            ) : (
              <p className="text-xs break-keep text-muted-foreground">
                회원 동의를 받는 문서가 아니라 게시해도 재동의를 요청하지 않아요.
              </p>
            )}

            {/* 경고만 한다 — 회원에게 불리한 변경인지는 운영자가 판단한다. */}
            <div aria-live="polite">
              {isShortNotice && (
                <p className="rounded-lg border border-border bg-secondary p-3 text-sm break-keep text-foreground">
                  회원에게 불리한 변경이면 시행일 {ADVERSE_CHANGE_NOTICE_DAYS}일 전에 공지해야 합니다.{" "}
                  {isScheduled ? `지금은 시행일까지 ${daysUntilEffective}일이에요.` : "지금은 즉시 시행이에요."}
                </p>
              )}
            </div>
          </DialogBody>

          <DialogFooter className="items-center">
            {isBlockedByMissingNotice && (
              <p id={`${id}-submit-reason`} className="text-xs break-keep text-muted-foreground sm:mr-auto">
                재동의를 받는 판은 변경 안내가 있어야 해요. 편집기에서 변경 안내를 쓰고 저장하세요.
              </p>
            )}
            <Button type="button" variant="outline" autoFocus onClick={() => call.end(false)}>
              취소
            </Button>
            <Button
              type="submit"
              // 안내가 없어 막힌 동안은 오래 머무는 비활성이라 무채색으로 둔다(누를 수 있는 버튼처럼 읽히지 않게).
              className={isBlockedByMissingNotice ? RESTING_DISABLED_PRIMARY_CLASS : undefined}
              disabled={isSubmitting || isBlockedByMissingNotice}
              aria-describedby={isBlockedByMissingNotice ? `${id}-submit-reason` : undefined}
            >
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
