import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { createCallable } from "react-call";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { adminContentKeys, type ContentActionReasonCategory } from "@/entities/admin-content";
import {
  useAdjustCloverMutation,
  useSetRateLimitExemptMutation,
  useSuspendUserMutation,
  useUnsuspendUserMutation,
  useWarnUserMutation,
} from "@/entities/admin-user";
import { isReportReasonCategory, REPORT_REASON_OPTIONS, REPORT_REASON_VALUES } from "@/entities/report";
import { isApiError } from "@/shared/lib/api/client";

type UserActionType =
  | "warn"
  | "suspend"
  | "unsuspend"
  | "rate-limit-exempt-on"
  | "rate-limit-exempt-off"
  | "clover-grant"
  | "clover-revoke";

const ACTION_TITLE: Record<UserActionType, string> = {
  warn: "경고",
  suspend: "정지",
  unsuspend: "정지 해제",
  "rate-limit-exempt-on": "레이트리밋 면제",
  "rate-limit-exempt-off": "면제 해제",
  "clover-grant": "클로버 지급",
  "clover-revoke": "클로버 회수",
};

/** BE는 지급·회수를 **부호 있는 `amount` 한 필드**로 받지만 화면은
 * 둘을 별개 조치로 나눈다 — `rate-limit-exempt-on`/`-off`와 같은 모양이다.
 * 🔴 운영자가 `-`를 손으로 치게 하면 **빠뜨렸을 때 회수가 지급이 되어 돈이 반대로 움직인다.**
 * 여기서 입력은 항상 양수이고 부호는 제출 시점에 이 표가 붙인다. */
const IS_CLOVER_ACTION: Record<UserActionType, boolean> = {
  warn: false,
  suspend: false,
  unsuspend: false,
  "rate-limit-exempt-on": false,
  "rate-limit-exempt-off": false,
  "clover-grant": true,
  "clover-revoke": true,
};

/** BE의 `AdminUserCloverRequest.amount` 범위가 `±100,000`이라 양수 입력의 상한도 같다
 * (현재 `CHAT_TURN_COST`·`ATTENDANCE_GRANT_AMOUNT` 기준 100,000클로버 = 채팅 10,000턴 = 출석 1,000일치).
 * 상한의 목적은 큰 보상을 막는 게 아니라 **자릿수 오입력을 거르는 그물**이고, 더 필요하면
 * 나눠 주는 편이 감사 로그에도 낫다. */
const CLOVER_AMOUNT_MAX = 100_000;

/** 사유 카테고리를 요구하는 조치는 `Notification`을 만드는 둘(경고·정지)뿐이다 — 나머지는 유저에게
 * 나가는 통지가 없어 사유를 인용할 자리가 없고, 대신 관리자 코멘트가 필수다(빈 값이면 BE가 422).
 * 컴포넌트와 `createUserActionSchema` 둘 다 이 한 곳을 보므로 규칙이 갈릴 수 없고, `Record`라
 * 새 조치를 추가하면 여기 키가 빠진 것이 컴파일 에러로 잡힌다. */
const IS_REASON_CATEGORY_REQUIRED: Record<UserActionType, boolean> = {
  warn: true,
  suspend: true,
  unsuspend: false,
  "rate-limit-exempt-on": false,
  "rate-limit-exempt-off": false,
  "clover-grant": false,
  "clover-revoke": false,
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

/** 같은 키가 두 번 도착했다는 뜻이다(더블클릭·네트워크 재시도) — BE가 두 번째를 막았으므로
 * 잔액은 한 번만 움직였다. "실패했다"고 말하면 운영자가 다시 누르게 되니 사실대로 말한다. */
const CLOVER_DUPLICATE_MESSAGE = "이미 처리된 요청이에요. 잔액은 한 번만 반영됐어요.";

const userActionSchema = z.object({
  reasonCategory: z.enum(REPORT_REASON_VALUES).optional(),
  adminComment: z.string(),
  // 폼의 숫자 입력은 `register(..., { valueAsNumber: true })`가 저장소 관례다(`build-story`의
  // StatTab·EndingTab). `z.coerce.number()`는 라우트 search param 쪽 관례인데 입력 타입이
  // `unknown`이라 RHF resolver와 안 맞는다 — 다른 문제다.
  //
  // 🔴 `z.number()` 하나로 두면 **클로버가 아닌 조치 다섯이 제출 불가가 된다.** 그 조치들은
  // 수량 입력을 렌더하지 않아 값이 `undefined`로 남고, 빈 칸은 `valueAsNumber`가 `NaN`으로
  // 주는데 `z.number()`가 둘 다 `invalid_type`으로 거부해 **`superRefine`이 실행조차 안 된다**
  // (zod 4.4.3으로 직접 확인). 게다가 에러 문구 렌더가 `isCloverAction` 블록 안이라 운영자에겐
  // "확정을 눌러도 아무 일이 없는" 상태로 보인다. 그래서 여기서는 **타입만 통과**시키고
  // 필수·범위·정수 검사는 전부 아래 `superRefine`이 조치별로 진다.
  cloverAmount: z.union([z.number(), z.nan()]).optional(),
});

type UserActionFormValues = z.infer<typeof userActionSchema>;

type UserActionConfirmModalProps = {
  userId: string;
  action: UserActionType;
  restrictableContentCount: number;
};

/** ContentActionConfirmModal과 같은 결 — `warn`/`suspend`는 사유 카테고리가 필수다. `unsuspend`는
 * `Notification`을 만들지 않아 사유 카테고리를 고를 근거가 없다 — 대신 관리자 코멘트가 필수다
 * (비어 있으면 API가 422). 콘텐츠명 정확 입력 같은 강한 확인은 넣지 않는다 — 정지·해제는 멱등이고
 * 가역이다(콘텐츠 조치도 그 확인을 되돌릴 수 없는 삭제에만 쓴다). `suspend`는 실제로 이용제한으로 전환될
 * 작품 개수(상세 응답의 `restrictableContentCount` — 이미 restricted/deleted인 작품은 제외한 값)를
 * 미리 보여주고, 성공 시 응답의 `restrictedContentCount`로 실제 내려간 개수를 toast에 담는다.
 * 두 값은 항상 일치해야 정지 확인의 예고가 사실과 맞는다. */
export const UserActionConfirmModal = createCallable<UserActionConfirmModalProps, void>(
  ({ call, userId, action, restrictableContentCount }) => {
    const queryClient = useQueryClient();
    const warnMutation = useWarnUserMutation(userId);
    const suspendMutation = useSuspendUserMutation(userId);
    const unsuspendMutation = useUnsuspendUserMutation(userId);
    const setRateLimitExemptMutation = useSetRateLimitExemptMutation(userId);
    const adjustCloverMutation = useAdjustCloverMutation(userId);
    const {
      control,
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<UserActionFormValues>({
      resolver: zodResolver(createUserActionSchema(action)),
      defaultValues: { reasonCategory: undefined, adminComment: "", cloverAmount: undefined },
    });

    const isReasonCategoryRequired = IS_REASON_CATEGORY_REQUIRED[action];
    const isCloverAction = IS_CLOVER_ACTION[action];

    const onSubmit = async (values: UserActionFormValues) => {
      try {
        if (action === "warn") {
          if (!values.reasonCategory) return;
          await warnMutation.mutateAsync(formToReasonedRequest(values, values.reasonCategory));
          toast.success("경고를 부과했어요.");
        } else if (action === "suspend") {
          if (!values.reasonCategory) return;
          const result = await suspendMutation.mutateAsync(formToReasonedRequest(values, values.reasonCategory));
          toast.success(`정지했어요. 작품 ${result.restrictedContentCount}건이 이용제한으로 전환됐어요.`);
        } else if (action === "unsuspend") {
          await unsuspendMutation.mutateAsync(formToCommentOnlyRequest(values));
          toast.success("정지를 해제했어요.");
        } else if (action === "rate-limit-exempt-on") {
          await setRateLimitExemptMutation.mutateAsync({ exempt: true, ...formToCommentOnlyRequest(values) });
          toast.success("레이트리밋을 면제했어요.");
        } else if (action === "rate-limit-exempt-off") {
          await setRateLimitExemptMutation.mutateAsync({ exempt: false, ...formToCommentOnlyRequest(values) });
          toast.success("레이트리밋 면제를 해제했어요.");
        } else if (action === "clover-grant" || action === "clover-revoke") {
          // 스키마가 `optional()`이라 타입이 `number | undefined`다 — `superRefine`을 통과한 뒤라
          // 클로버 경로에서는 반드시 값이 있지만 타입체커는 그걸 모른다. `reasonCategory`를
          // 좁히는 위 두 분기와 같은 모양으로 막는다.
          const cloverAmount = values.cloverAmount;
          if (cloverAmount === undefined) return;
          const amount = action === "clover-grant" ? cloverAmount : -cloverAmount;
          await adjustCloverMutation.mutateAsync({
            amount,
            // 🔴 요청마다 새로 만든다. 같은 어드민이 같은 유저에게
            // 같은 금액을 의도적으로 두 번 줄 수 있어야 하므로 `(user, 금액)`으로 파생하면 안 된다.
            // 이 모달은 확정 1회당 한 번 제출되므로 여기가 "한 번 누름"의 경계다.
            idempotencyKey: crypto.randomUUID(),
            ...formToCommentOnlyRequest(values),
          });
          toast.success(
            action === "clover-grant"
              ? `클로버 ${cloverAmount.toLocaleString("ko-KR")}개를 지급했어요.`
              : `클로버 ${cloverAmount.toLocaleString("ko-KR")}개를 회수했어요.`,
          );
        } else {
          assertNever(action);
        }
        // 경고·정지·정지 해제는 작품 상태를 바꿀 수 있다 — 유저 쿼리는 각 뮤테이션이 끊고, 작품
        // 쿼리는 entity끼리 물리지 않도록 여기서 끊는다. 레이트리밋 면제 토글은 작품을 건드리지
        // 않아 끊을 게 없지만, 조치별로 가르면 이 한 줄이 분기 다섯 개로 흩어져 그대로 둔다
        // (무효화는 멱등하고 상세 화면의 작품 쿼리는 한 벌뿐이다).
        void queryClient.invalidateQueries({ queryKey: adminContentKeys.all });
        call.end();
      } catch (error) {
        // 클로버는 실패 두 가지가 서로 다른 행동을 부른다 — 409는 "다시 누르지 마라"(이미 됐다),
        // 422는 "금액을 고쳐라"(잔액보다 크다). 한 문구로 뭉치면 운영자가 둘 다 재시도한다.
        const status = isApiError(error) ? error.status : null;
        if (isCloverAction && status === 409) {
          toast.success(CLOVER_DUPLICATE_MESSAGE);
          call.end();
          return;
        }
        if (isCloverAction && status === 422) {
          toast.error("현재 잔액보다 많이 회수할 수 없어요.");
          return;
        }
        toast.error(ERROR_MESSAGE);
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{ACTION_TITLE[action]}</DialogTitle>
            <DialogDescription>
              {action === "warn" && "이 유저에게 경고를 부과합니다."}
              {action === "suspend" &&
                (restrictableContentCount > 0
                  ? `이 유저를 정지합니다. 작품 ${restrictableContentCount}건이 함께 이용제한으로 전환됩니다.`
                  : "이 유저를 정지합니다.")}
              {action === "unsuspend" && "이 유저의 정지를 해제합니다. 작품은 이용제한 상태로 남습니다."}
              {action === "rate-limit-exempt-on" &&
                "이 유저를 일일 상한과 이미지 토큰 상한에서 면제합니다. 분당 상한과 이미지 동시 생성 1건은 그대로 적용됩니다."}
              {action === "rate-limit-exempt-off" &&
                "이 유저에게 일일 상한과 이미지 토큰 상한을 다시 적용합니다. 분당 상한과 이미지 동시 생성 1건은 면제 중에도 적용되고 있었습니다."}
              {action === "clover-grant" && "이 유저에게 클로버를 지급합니다. 무료 일일 한도를 넘긴 뒤에 쓰입니다."}
              {action === "clover-revoke" &&
                "이 유저의 클로버를 회수합니다. 현재 잔액보다 많이 회수할 수는 없습니다."}
            </DialogDescription>
          </DialogHeader>

          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex flex-col gap-3"
          >
            {isReasonCategoryRequired && (
              <div className="flex flex-col gap-1.5">
                <Label>사유 카테고리</Label>
                <Controller
                  name="reasonCategory"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value ?? ""}
                      onValueChange={(value) => field.onChange(isReportReasonCategory(value) ? value : undefined)}
                    >
                      <SelectTrigger
                        className="w-full"
                        aria-label="사유 카테고리"
                        aria-invalid={!!errors.reasonCategory}
                        aria-describedby={errors.reasonCategory ? "user-action-reason-error" : undefined}
                      >
                        <SelectValue placeholder="사유를 선택하세요" />
                      </SelectTrigger>
                      <SelectContent>
                        {REPORT_REASON_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
                {errors.reasonCategory && (
                  <p id="user-action-reason-error" role="alert" className="text-xs text-destructive-text">
                    {errors.reasonCategory.message}
                  </p>
                )}
              </div>
            )}

            {isCloverAction && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="user-action-clover-amount">
                  {action === "clover-grant" ? "지급 수량" : "회수 수량"}
                </Label>
                <Input
                  id="user-action-clover-amount"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={CLOVER_AMOUNT_MAX}
                  step={1}
                  placeholder="1 이상"
                  className="tabular-nums"
                  aria-invalid={!!errors.cloverAmount}
                  aria-describedby={
                    errors.cloverAmount ? "user-action-clover-amount-error" : "user-action-clover-amount-hint"
                  }
                  {...register("cloverAmount", { valueAsNumber: true })}
                />
                {errors.cloverAmount ? (
                  <p id="user-action-clover-amount-error" role="alert" className="text-xs text-destructive-text">
                    {errors.cloverAmount.message}
                  </p>
                ) : (
                  <p id="user-action-clover-amount-hint" className="text-xs text-muted-foreground">
                    최대 {CLOVER_AMOUNT_MAX.toLocaleString("ko-KR")}개까지 한 번에{" "}
                    {action === "clover-grant" ? "지급" : "회수"}할 수 있어요.
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="user-action-comment">
                관리자 코멘트 {isReasonCategoryRequired ? "(선택)" : "(필수)"}
              </Label>
              <Textarea
                id="user-action-comment"
                placeholder={isReasonCategoryRequired ? "유저에게 전달할 코멘트" : "사유를 입력하세요"}
                rows={3}
                aria-invalid={!!errors.adminComment}
                aria-describedby={errors.adminComment ? "user-action-comment-error" : undefined}
                {...register("adminComment")}
              />
              {errors.adminComment && (
                <p id="user-action-comment-error" role="alert" className="text-xs text-destructive-text">
                  {errors.adminComment.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end()}>
                취소
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "처리 중..." : "조치 확정"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);

/** warn·suspend는 사유 카테고리가 필수다 — 스키마가 그걸 보장한 뒤에만 호출된다. */
function formToReasonedRequest(values: UserActionFormValues, reasonCategory: ContentActionReasonCategory) {
  return { reasonCategory, adminComment: values.adminComment.trim() || undefined };
}

/** 사유 카테고리를 받지 않는 조치(정지 해제·레이트리밋 면제 토글)는 코멘트가 필수다(빈 값이면 BE가 422). */
function formToCommentOnlyRequest(values: UserActionFormValues) {
  return { adminComment: values.adminComment.trim() };
}

/** 조치별로 필수 필드가 갈린다 — 그 규칙을 컴포넌트가 아니라 스키마 한 곳에 둔다. */
function createUserActionSchema(action: UserActionType) {
  return userActionSchema.superRefine((values, ctx) => {
    if (!IS_REASON_CATEGORY_REQUIRED[action]) {
      if (values.adminComment.trim().length === 0) {
        ctx.addIssue({ code: "custom", path: ["adminComment"], message: "사유를 입력해주세요." });
      }
    } else if (!values.reasonCategory) {
      ctx.addIssue({ code: "custom", path: ["reasonCategory"], message: "사유 카테고리를 선택해주세요." });
    }

    // 클로버가 아닌 조치에서 `cloverAmount`는 입력 자체가 렌더되지 않아 `undefined`다 — 그 값을
    // 쓰지 않으므로 검사하지 않는다(스키마가 `optional()`인 이유). 클로버일 때만 BE의 `amount`
    // 제약(정수, 0 거부, ±100,000)을 화면에서 먼저 건다. 빈 칸은 `valueAsNumber`가 `NaN`으로 주고
    // `Number.isFinite`가 `undefined`·`NaN`을 함께 잡는다.
    if (!IS_CLOVER_ACTION[action]) return;
    // `Number.isFinite`는 타입을 좁히지 않는다 — `undefined`(입력 미렌더)와 `NaN`(빈 칸)을 한
    // 조건으로 걸러낸 뒤, 아래 비교가 `number`를 보도록 지역 변수로 받는다.
    const amount = values.cloverAmount;
    if (amount === undefined || !Number.isFinite(amount)) {
      ctx.addIssue({ code: "custom", path: ["cloverAmount"], message: "수량을 입력해주세요." });
      return;
    }
    if (!Number.isInteger(amount)) {
      ctx.addIssue({ code: "custom", path: ["cloverAmount"], message: "클로버는 정수로만 주고받아요." });
      return;
    }
    // 0을 따로 막는 이유: BE의 `amount`는 부호로 방향을 가르므로 0이면 방향이 없다. 화면이
    // 양수만 받으니 0과 음수가 같은 메시지로 떨어져도 운영자가 할 일은 하나다.
    if (amount < 1) {
      ctx.addIssue({ code: "custom", path: ["cloverAmount"], message: "1 이상을 입력해주세요." });
      return;
    }
    if (amount > CLOVER_AMOUNT_MAX) {
      ctx.addIssue({
        code: "custom",
        path: ["cloverAmount"],
        message: `한 번에 ${CLOVER_AMOUNT_MAX.toLocaleString("ko-KR")}개까지만 가능해요.`,
      });
    }
  });
}

function assertNever(value: never): never {
  throw new Error(`Unexpected: ${String(value)}`);
}
