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
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { adminContentKeys, type ContentActionReasonCategory } from "@/entities/admin-content";
import {
  useAdjustCloverMutation,
  useSetBetaMutation,
  useSetNovelizeGrantMutation,
  useSetPremiumModelsGrantMutation,
  useSetRateLimitExemptMutation,
  useSuspendUserMutation,
  useUnsuspendUserMutation,
  useWarnUserMutation,
  type PremiumModelsGrantScope,
} from "@/entities/admin-user";
import { isReportReasonCategory, REPORT_REASON_OPTIONS, REPORT_REASON_VALUES } from "@/entities/report";
import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

type UserActionType =
  | "warn"
  | "suspend"
  | "unsuspend"
  | "rate-limit-exempt-on"
  | "rate-limit-exempt-off"
  | "beta-on"
  | "beta-off"
  | "novelize-on"
  | "novelize-off"
  | "chat-premium-models-on"
  | "chat-premium-models-off"
  | "novelize-premium-models-on"
  | "novelize-premium-models-off"
  | "clover-grant"
  | "clover-revoke";

const ACTION_TITLE: Record<UserActionType, string> = {
  warn: "경고",
  suspend: "정지",
  unsuspend: "정지 해제",
  "rate-limit-exempt-on": "레이트리밋 면제",
  "rate-limit-exempt-off": "면제 해제",
  "beta-on": "베타 지정",
  "beta-off": "베타 해제",
  "novelize-on": "소설화 허용",
  "novelize-off": "소설화 회수",
  "chat-premium-models-on": "채팅 상위 모델 허용",
  "chat-premium-models-off": "채팅 상위 모델 회수",
  "novelize-premium-models-on": "소설화 상위 모델 허용",
  "novelize-premium-models-off": "소설화 상위 모델 회수",
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
  "beta-on": false,
  "beta-off": false,
  "novelize-on": false,
  "novelize-off": false,
  "chat-premium-models-on": false,
  "chat-premium-models-off": false,
  "novelize-premium-models-on": false,
  "novelize-premium-models-off": false,
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
  "beta-on": false,
  "beta-off": false,
  "novelize-on": false,
  "novelize-off": false,
  "chat-premium-models-on": false,
  "chat-premium-models-off": false,
  "novelize-premium-models-on": false,
  "novelize-premium-models-off": false,
  "clover-grant": false,
  "clover-revoke": false,
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

/** 같은 키가 두 번 도착했다는 뜻이다(더블클릭·네트워크 재시도) — BE가 두 번째를 막았으므로
 * 잔액은 한 번만 움직였다. "실패했다"고 말하면 운영자가 다시 누르게 되니 사실대로 말한다. */
const CLOVER_DUPLICATE_MESSAGE = "이미 처리된 요청이에요. 잔액은 한 번만 반영됐어요.";

/** 베타는 성인만 받는다 — BE가 지정 시 만 19세 미만이거나 생년월일이 없으면 422로 거부한다. */
const BETA_AGE_RESTRICTED_MESSAGE = "만 19세 미만이거나 생년월일이 없는 유저라 베타 참가자로 지정할 수 없어요.";

/** 소설화 허용은 서버 설정의 시험 계정 명단 안에만 줄 수 있다 — 처리방침이 소설화를 싣기 전까지 허용을 그 안에 가둔다.
 * 명단은 어드민 화면에서 고칠 수 없어 운영자가 할 일은 "명단부터 바꿔야 한다"를 아는 것뿐이다. */
const NOVELIZE_GRANT_NOT_ALLOWLISTED_MESSAGE =
  "소설화 시험 명단에 없는 유저라 허용할 수 없어요. 서버 명단에 먼저 넣어야 해요.";

/** 상위 모델 허용도 같은 이유로 기능마다 따로 있는 서버 명단 안에만 줄 수 있다 — 채팅 명단에 있어도 소설화 명단에는 없을 수 있다. */
const PREMIUM_MODELS_GRANT_REJECTION = {
  chat: {
    code: "CHAT_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED",
    message: "채팅 상위 모델 시험 명단에 없는 유저라 허용할 수 없어요. 서버 명단에 먼저 넣어야 해요.",
  },
  novelize: {
    code: "NOVELIZE_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED",
    message: "소설화 상위 모델 시험 명단에 없는 유저라 허용할 수 없어요. 서버 명단에 먼저 넣어야 해요.",
  },
} as const;

const PREMIUM_MODELS_GRANT_SUCCESS = {
  chat: { on: "채팅 상위 모델을 허용했어요.", off: "채팅 상위 모델 허용을 회수했어요." },
  novelize: { on: "소설화 상위 모델을 허용했어요.", off: "소설화 상위 모델 허용을 회수했어요." },
} as const;

type PremiumModelsGrantAction =
  | "chat-premium-models-on"
  | "chat-premium-models-off"
  | "novelize-premium-models-on"
  | "novelize-premium-models-off";

/** 상위 모델 토글 넷을 (채팅/소설화, 허용/회수)로 푼다 — 제출 분기 하나가 넷을 함께 받는다. */
const PREMIUM_MODELS_GRANT: Record<PremiumModelsGrantAction, { scope: PremiumModelsGrantScope; granted: boolean }> = {
  "chat-premium-models-on": { scope: "chat", granted: true },
  "chat-premium-models-off": { scope: "chat", granted: false },
  "novelize-premium-models-on": { scope: "novelize", granted: true },
  "novelize-premium-models-off": { scope: "novelize", granted: false },
};

function isPremiumModelsGrantAction(action: UserActionType): action is PremiumModelsGrantAction {
  return action in PREMIUM_MODELS_GRANT;
}

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
  restorableContentCount: number;
  /** 조치가 반영돼 모달이 닫힌 뒤 부른다 — 상세 레이아웃이 하단 시트를 닫는다. 고칠 입력이 없는 거부(베타 나이 제한·소설화·상위 모델 명단 밖)는
   * 바뀐 것이 없어 부르지 않는다. */
  onSuccess?: () => void;
};

/** ContentActionConfirmModal과 같은 결 — `warn`/`suspend`는 사유 카테고리가 필수다. `unsuspend`는
 * `Notification`을 만들지 않아 사유 카테고리를 고를 근거가 없다 — 대신 관리자 코멘트가 필수다
 * (비어 있으면 API가 422). 콘텐츠명 정확 입력 같은 강한 확인은 넣지 않는다 — 정지·해제는 멱등이고
 * 가역이다(콘텐츠 조치도 그 확인을 되돌릴 수 없는 삭제에만 쓴다). `suspend`는 실제로 이용제한으로 전환될
 * 작품 개수(상세 응답의 `restrictableContentCount` — 이미 restricted/deleted인 작품은 제외한 값)를
 * 미리 보여주고, 성공 시 응답의 `restrictedContentCount`로 실제 내려간 개수를 toast에 담는다.
 * 두 값은 항상 일치해야 정지 확인의 예고가 사실과 맞는다. `unsuspend`도 같은 모양이다 — 정지로 이용제한됐다가
 * 해제로 정상으로 돌아올 작품 수(`restorableContentCount`)를 예고하고, 응답의 `restoredContentCount`를 toast에 담는다. */
export const UserActionConfirmModal = createCallable<UserActionConfirmModalProps, void>(
  ({ call, userId, action, restrictableContentCount, restorableContentCount, onSuccess }) => {
    const queryClient = useQueryClient();
    const warnMutation = useWarnUserMutation(userId);
    const suspendMutation = useSuspendUserMutation(userId);
    const unsuspendMutation = useUnsuspendUserMutation(userId);
    const setRateLimitExemptMutation = useSetRateLimitExemptMutation(userId);
    const setBetaMutation = useSetBetaMutation(userId);
    const setNovelizeGrantMutation = useSetNovelizeGrantMutation(userId);
    const setPremiumModelsGrantMutation = useSetPremiumModelsGrantMutation(userId);
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
    const premiumModelsGrant = isPremiumModelsGrantAction(action) ? PREMIUM_MODELS_GRANT[action] : null;

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
          const result = await unsuspendMutation.mutateAsync(formToCommentOnlyRequest(values));
          toast.success(
            result.restoredContentCount > 0
              ? `정지를 해제했어요. 작품 ${result.restoredContentCount}건이 정상으로 돌아왔어요.`
              : "정지를 해제했어요.",
          );
        } else if (action === "rate-limit-exempt-on") {
          await setRateLimitExemptMutation.mutateAsync({ exempt: true, ...formToCommentOnlyRequest(values) });
          toast.success("레이트리밋을 면제했어요.");
        } else if (action === "rate-limit-exempt-off") {
          await setRateLimitExemptMutation.mutateAsync({ exempt: false, ...formToCommentOnlyRequest(values) });
          toast.success("레이트리밋 면제를 해제했어요.");
        } else if (action === "beta-on") {
          await setBetaMutation.mutateAsync({ beta: true, ...formToCommentOnlyRequest(values) });
          toast.success("베타 참가자로 지정했어요.");
        } else if (action === "beta-off") {
          await setBetaMutation.mutateAsync({ beta: false, ...formToCommentOnlyRequest(values) });
          toast.success("베타 지정을 해제했어요.");
        } else if (action === "novelize-on") {
          await setNovelizeGrantMutation.mutateAsync({ granted: true, ...formToCommentOnlyRequest(values) });
          toast.success("소설화를 허용했어요.");
        } else if (action === "novelize-off") {
          await setNovelizeGrantMutation.mutateAsync({ granted: false, ...formToCommentOnlyRequest(values) });
          toast.success("소설화 허용을 회수했어요.");
        } else if (isPremiumModelsGrantAction(action)) {
          const grant = PREMIUM_MODELS_GRANT[action];
          await setPremiumModelsGrantMutation.mutateAsync({ ...grant, ...formToCommentOnlyRequest(values) });
          toast.success(PREMIUM_MODELS_GRANT_SUCCESS[grant.scope][grant.granted ? "on" : "off"]);
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
        onSuccess?.();
      } catch (error) {
        // 클로버는 실패 두 가지가 서로 다른 행동을 부른다 — 409는 "다시 누르지 마라"(이미 됐다),
        // 422는 "금액을 고쳐라"(잔액보다 크다). 한 문구로 뭉치면 운영자가 둘 다 재시도한다.
        const status = isApiError(error) ? error.status : null;
        if (isCloverAction && status === 409) {
          toast.success(CLOVER_DUPLICATE_MESSAGE);
          call.end();
          // 앞선 요청이 이미 반영했다 — 성공과 같은 결과라 시트도 닫는다.
          onSuccess?.();
          return;
        }
        if (isCloverAction && status === 422) {
          toast.error("현재 잔액보다 많이 회수할 수 없어요.");
          return;
        }
        // 같은 엔드포인트의 공백 코멘트·검증 실패도 422라 status만으로는 못 가른다 — `detail.code`로
        // 나이 거부만 골라낸다. 고칠 입력이 없는 거부라 모달은 닫는다(다시 눌러도 같은 결과다).
        if (action === "beta-on" && status === 422 && isBetaAgeRestricted(error)) {
          toast.error(BETA_AGE_RESTRICTED_MESSAGE);
          call.end();
          return;
        }
        // 명단 밖 거부도 같은 모양이다 — 공백 코멘트 422 와 `detail.code`로 가르고, 고칠 입력이 없어 모달을 닫는다.
        if (action === "novelize-on" && status === 422 && hasDetailCode(error, "NOVELIZE_GRANT_NOT_ALLOWLISTED")) {
          toast.error(NOVELIZE_GRANT_NOT_ALLOWLISTED_MESSAGE);
          call.end();
          return;
        }
        if (premiumModelsGrant?.granted && status === 422) {
          const rejection = PREMIUM_MODELS_GRANT_REJECTION[premiumModelsGrant.scope];
          if (hasDetailCode(error, rejection.code)) {
            toast.error(rejection.message);
            call.end();
            return;
          }
        }
        toast.error(ERROR_MESSAGE);
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle>{ACTION_TITLE[action]}</DialogTitle>
            <DialogDescription>
              {action === "warn" && "이 유저에게 경고를 부과합니다."}
              {action === "suspend" &&
                (restrictableContentCount > 0
                  ? `이 유저를 정지합니다. 작품 ${restrictableContentCount}건이 함께 이용제한으로 전환됩니다.`
                  : "이 유저를 정지합니다.")}
              {action === "unsuspend" &&
                (restorableContentCount > 0
                  ? `이 유저의 정지를 해제합니다. 정지로 이용제한된 작품 ${restorableContentCount}건이 함께 정상으로 돌아갑니다. 신고나 직접 조치로 제한된 작품은 그대로입니다.`
                  : "이 유저의 정지를 해제합니다. 신고나 직접 조치로 제한된 작품은 그대로입니다.")}
              {action === "rate-limit-exempt-on" &&
                "이 유저를 일일 상한과 이미지 토큰 상한에서 면제합니다. 분당 상한과 이미지 동시 생성 1건은 그대로 적용됩니다."}
              {action === "rate-limit-exempt-off" &&
                "이 유저에게 일일 상한과 이미지 토큰 상한을 다시 적용합니다. 분당 상한과 이미지 동시 생성 1건은 면제 중에도 적용되고 있었습니다."}
              {action === "beta-on" &&
                "이 유저를 베타 참가자로 지정합니다. 만 19세 이상만 지정할 수 있습니다. 이미 지정된 유저면 처음 지정한 시각이 유지됩니다."}
              {action === "beta-off" &&
                "이 유저의 베타 지정을 해제합니다. 다시 지정하면 그때가 새 지정 시각이 됩니다."}
              {action === "novelize-on" &&
                "이 유저에게 소설화를 허용합니다. 서버의 시험 계정 명단 안에 있는 유저만 허용할 수 있고, 전역 스위치가 꺼져 있으면 허용해도 아직 쓸 수 없습니다. 이미 허용된 유저면 처음 허용한 시각이 유지됩니다."}
              {action === "novelize-off" &&
                "이 유저의 소설화 허용을 회수합니다. 이미 만든 소설은 지워지지 않습니다. 다시 허용하기 전까지 사용자 화면에서 소설을 열거나 지울 수 없어, 삭제 요청은 문의나 탈퇴로 처리합니다. 다시 허용하면 그때가 새 허용 시각이 됩니다."}
              {action === "chat-premium-models-on" &&
                "이 유저가 채팅방에서 상위 글쓰기 모델(Claude)을 고를 수 있게 합니다. 서버의 시험 계정 명단 안에 있는 유저만 허용할 수 있고, 전역 스위치가 꺼져 있으면 허용해도 아직 쓸 수 없습니다. 상위 모델 턴은 레이트리밋 면제 유저도 클로버를 냅니다. 이미 허용된 유저면 처음 허용한 시각이 유지됩니다."}
              {action === "chat-premium-models-off" &&
                "이 유저의 채팅 상위 모델 허용을 회수합니다. 상위 모델을 고른 방은 막히지 않고 다음 턴부터 Gemini 로, Gemini 가격에 돕니다. 진행 중이던 턴은 이미 값을 낸 모델로 끝납니다. 다시 허용하면 방에 저장된 모델로 돌아갑니다."}
              {action === "novelize-premium-models-on" &&
                "이 유저가 소설 장을 만들 때 상위 글쓰기 모델(Claude)을 고를 수 있게 합니다. 소설화 허용도 있어야 보이고, 서버의 시험 계정 명단 안에 있는 유저만 허용할 수 있으며, 전역 스위치가 꺼져 있으면 허용해도 아직 쓸 수 없습니다. 이미 허용된 유저면 처음 허용한 시각이 유지됩니다."}
              {action === "novelize-premium-models-off" &&
                "이 유저의 소설화 상위 모델 허용을 회수합니다. 이후 상위 모델로 장을 요청하면 거부됩니다(Gemini 로 바꿔 만들지 않습니다). 회수 전에 값을 낸 장 작업은 그 모델로 끝납니다."}
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
              <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
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

/** 사유 카테고리를 받지 않는 조치(정지 해제·레이트리밋 면제·베타 토글·소설화·상위 모델 토글)는 코멘트가 필수다(빈 값이면 BE가 422). */
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

/** 나이 거부 code는 OpenAPI에 노출되지 않아 생성 타입이 없다 — 구조화 dict `detail`을 직접 읽는다
 * (`PublishPromptSetDialog`의 `"rule" in error.detail`과 같은 모양). */
function isBetaAgeRestricted(error: unknown) {
  return hasDetailCode(error, "BETA_AGE_RESTRICTED");
}

/** 거부 code 가 OpenAPI 에 없는 422 들(베타 나이·소설화·상위 모델 명단)을 `detail.code`로 가른다. */
function hasDetailCode(error: unknown, code: string) {
  if (!isApiError(error) || typeof error.detail !== "object" || error.detail === null) return false;
  return "code" in error.detail && error.detail.code === code;
}

function assertNever(value: never): never {
  throw new Error(`Unexpected: ${String(value)}`);
}
