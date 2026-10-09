import { useId, useState, type ComponentProps } from "react";
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
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { Controller, useForm } from "react-hook-form";

import { CloverProductLine, type CloverProductItem } from "@/entities/clover";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import { findPayMethod, formatPayMethodLabel, toPayMethodKey, type CloverPayMethodItem } from "../model/payMethod";
import {
  getPurchaseFormDefaultValues,
  purchaseFormSchema,
  type PurchaseFormValues,
} from "../model/purchaseForm";
import { PURCHASE_MESSAGES, type PurchaseResult } from "../model/purchaseResult";
import { announcePurchaseResult } from "../model/usePaymentRedirect";
import { usePurchaseClover } from "../model/usePurchaseClover";

const INLINE_LINK_CLASS = "font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline focus-visible:underline";

type PurchaseConfirmDialogProps = {
  product: CloverProductItem;
  payMethods: CloverPayMethodItem[];
  /** 계정 이메일. 구매자 이메일 칸을 미리 채운다. */
  email: string;
};

/** 다이얼로그 안에 남는 결과 — 고쳐서 다시 누를 수 있거나(완료되지 않음), 다시 눌러도 같아 이유를 읽어야 하는 것. */
type DialogNotice = Extract<PurchaseResult, "notCompleted" | "ageRestricted" | "unavailable" | "failed" | "sdkUnavailable">;

/** 클로버 구매 확인. 결제수단·구매자 정보·유료 조건 동의를 받아 주문 → 결제창 → 확정을 한 번에 돈다. 호출부(허브)가
 * 하나뿐이고 끝난 뒤 할 일(결과 안내 후 닫기)이 늘 같아 자체 호출형이다.
 *
 * 이 화면의 솔리드 채움은 "결제하기" 하나다 — 허브의 상품 카드는 고르기만 하는 outline 이라, 돈이 나가는
 * 확정만 이 다이얼로그 안에서 채움을 쓴다. 결제수단은 같은 이유로 틴트 목록(`list`)이다.
 *
 * 고칠 수 있는 결과(창을 닫음·나이 제한·결제 중단·SDK 실패)는 다이얼로그를 열어 둔 채 본문 끝에 문장으로 남긴다 —
 * 입력한 구매자 정보를 다시 치지 않게. 지급이 끝났거나 확인 중이면 닫고 토스트로 알린다. */
export const PurchaseConfirmDialog = createCallable<PurchaseConfirmDialogProps, void>(
  ({ call, product, payMethods, email }) => {
    const fieldId = useId();
    const [firstPayMethod] = payMethods;
    const form = useForm<PurchaseFormValues>({
      resolver: zodResolver(purchaseFormSchema),
      defaultValues: getPurchaseFormDefaultValues(email, firstPayMethod ? toPayMethodKey(firstPayMethod) : ""),
    });
    const { errors, isSubmitting } = form.formState;
    const { purchase } = usePurchaseClover();
    const [notice, setNotice] = useState<DialogNotice | null>(null);
    // 결제창이 떠 있는 동안 다이얼로그를 내린다. Radix 모달은 열린 동안 바깥의 포인터를 끄고 포커스를 안에 가두는데,
    // 결제창은 body 에 붙는 포트원 iframe 이라 다이얼로그가 떠 있으면 누를 수도 입력할 수도 없다. 폼 상태는 이 컴포넌트가
    // 쥐고 있어 다시 열면 입력이 그대로다.
    const [isCheckoutOpen, setIsCheckoutOpen] = useState(false);

    async function handleValidSubmit(values: PurchaseFormValues) {
      setNotice(null);
      const payMethod = findPayMethod(payMethods, values.payMethodKey);
      if (!payMethod) {
        form.setError("payMethodKey", { message: "결제수단을 골라 주세요" });
        return;
      }
      const result = await purchase({
        productKey: product.key,
        payMethod,
        values,
        onCheckoutOpen: () => setIsCheckoutOpen(true),
      });
      // 리다이렉트는 페이지가 떠나는 중이라 다시 띄우지 않는다.
      if (result !== "redirecting") setIsCheckoutOpen(false);
      switch (result) {
        case "paid":
        case "checking":
        case "problem":
          announcePurchaseResult(result);
          call.end();
          return;
        // 세션을 다시 읽어 허브가 본인인증 안내로, 앱이 재동의 모달로 바뀐다(전역 뮤테이션 처리). 다이얼로그에 남을
        // 이유가 없다.
        case "identityRequired":
        case "reconsentRequired":
          call.end();
          return;
        // 결제창이 페이지를 떠난다. 돌아오면 허브가 쿼리로 이어받는다.
        case "redirecting":
          return;
        default:
          setNotice(result);
      }
    }

    const payMethodErrorId = `${fieldId}-pay-method-error`;

    return (
      <Dialog open={!call.ended && !isCheckoutOpen} onOpenChange={(isOpen) => !isOpen && !isSubmitting && call.end()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>클로버 구매</DialogTitle>
            <DialogDescription className="break-keep">
              결제창에서 결제를 마치면 클로버가 바로 지급돼요.
            </DialogDescription>
          </DialogHeader>

          {/* 폼이 본문과 푸터를 함께 감싼다(결제하기가 submit 이라). 남은 높이를 받아 본문만 스크롤한다. */}
          <form
            className="flex min-h-0 flex-1 flex-col gap-4"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              // 결제 중 `disabled` 는 누른 버튼의 포커스를 날린다 — `aria-disabled` 로 두고 여기서 막는다.
              if (isSubmitting) return;
              void form.handleSubmit(handleValidSubmit)(event);
            }}
          >
            <DialogBody className="flex flex-col gap-5">
              <div className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
                <CloverProductLine product={product} />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label id={`${fieldId}-pay-method`}>결제수단</Label>
                <Controller
                  control={form.control}
                  name="payMethodKey"
                  render={({ field }) => (
                    // `hover:bg-secondary` — 프리미티브의 `hover:bg-muted` 는 모달(popover) 표면과 같은 값이라 사라진다.
                    <ToggleGroup
                      type="single"
                      variant="list"
                      value={field.value}
                      // Radix 단일선택은 선택한 항목을 다시 누르면 빈 문자열을 준다 — 선택을 유지한다.
                      onValueChange={(value) => value !== "" && field.onChange(value)}
                      aria-labelledby={`${fieldId}-pay-method`}
                      aria-invalid={!!errors.payMethodKey}
                      aria-describedby={errors.payMethodKey ? payMethodErrorId : undefined}
                      className="grid w-full grid-cols-2 gap-2 sm:grid-cols-3"
                    >
                      {payMethods.map((item) => (
                        <ToggleGroupItem
                          key={toPayMethodKey(item)}
                          value={toPayMethodKey(item)}
                          className="h-10 w-full hover:bg-secondary"
                        >
                          {formatPayMethodLabel(item)}
                        </ToggleGroupItem>
                      ))}
                    </ToggleGroup>
                  )}
                />
                {errors.payMethodKey && (
                  <p id={payMethodErrorId} role="alert" className="text-xs text-destructive-text">
                    {errors.payMethodKey.message}
                  </p>
                )}
              </div>

              <fieldset className="flex flex-col gap-3">
                <legend className="text-sm font-medium text-foreground">구매자 정보</legend>
                <p className="-mt-1.5 text-xs break-keep text-muted-foreground">
                  결제대행사가 요구하는 정보예요. 결제창에만 전달하고 저장하지 않아요.
                </p>
                <BuyerField
                  id={`${fieldId}-name`}
                  label="이름"
                  error={errors.fullName?.message}
                  inputProps={{ autoComplete: "name", ...form.register("fullName") }}
                />
                <BuyerField
                  id={`${fieldId}-phone`}
                  label="휴대폰 번호"
                  error={errors.phoneNumber?.message}
                  inputProps={{
                    type: "tel",
                    inputMode: "tel",
                    autoComplete: "tel",
                    placeholder: "010-0000-0000",
                    ...form.register("phoneNumber"),
                  }}
                />
                <BuyerField
                  id={`${fieldId}-email`}
                  label="이메일"
                  error={errors.email?.message}
                  inputProps={{ type: "email", autoComplete: "email", ...form.register("email") }}
                />
              </fieldset>

              <div className="flex flex-col gap-1.5">
                <Controller
                  control={form.control}
                  name="agreed"
                  render={({ field }) => (
                    <label className="flex items-start gap-2 text-sm break-keep text-foreground">
                      <Checkbox
                        className="mt-0.5"
                        checked={field.value}
                        onCheckedChange={(checked) => field.onChange(checked === true)}
                        aria-invalid={!!errors.agreed}
                        aria-describedby={errors.agreed ? `${fieldId}-agreed-error` : undefined}
                      />
                      <span>
                        결제한 클로버는 바로 제공돼, 쓴 만큼은 청약철회할 수 없다는 데 동의해요.{" "}
                        <span className="text-muted-foreground">(필수)</span>
                      </span>
                    </label>
                  )}
                />
                {errors.agreed && (
                  <p id={`${fieldId}-agreed-error`} role="alert" className="pl-6 text-xs text-destructive-text">
                    {errors.agreed.message}
                  </p>
                )}
                {/* 새 탭으로 연다 — 같은 탭에서 열면 입력한 구매자 정보와 이 다이얼로그를 잃는다. */}
                <p className="pl-6 text-xs break-keep text-muted-foreground">
                  남은 유료 클로버의 환불 기준은{" "}
                  <Link
                    to={SUPPORT_DESTINATIONS["refund-policy"].to}
                    target="_blank"
                    rel="noopener"
                    className={INLINE_LINK_CLASS}
                  >
                    {SUPPORT_DESTINATIONS["refund-policy"].label}
                  </Link>
                  에서 볼 수 있어요.
                </p>
              </div>

              {notice && <PurchaseNotice notice={notice} onLeave={() => call.end()} />}
            </DialogBody>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                aria-disabled={isSubmitting}
                className="aria-disabled:opacity-65"
                onClick={() => !isSubmitting && call.end()}
              >
                취소
              </Button>
              <Button type="submit" aria-disabled={isSubmitting} className="aria-disabled:opacity-65">
                {isSubmitting ? "결제 진행 중…" : `${product.priceKrw.toLocaleString()}원 결제하기`}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);

type BuyerFieldProps = {
  id: string;
  label: string;
  error: string | undefined;
  inputProps: ComponentProps<typeof Input>;
};

function BuyerField({ id, label, error, inputProps }: BuyerFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} aria-invalid={!!error} aria-describedby={error ? errorId : undefined} {...inputProps} />
      {error && (
        <p id={errorId} role="alert" className="text-xs text-destructive-text">
          {error}
        </p>
      )}
    </div>
  );
}

/** 다이얼로그에 남는 결과 문장. 결제창을 닫은 것은 실패가 아니라 중립 문장이고, 나머지는 이유를 읽어야 하는 거절이다.
 * SDK 를 못 불러왔으면 새로고침만이 길이라 그 버튼을, 다시 눌러도 같은 실패면 문의 링크를 붙인다. */
function PurchaseNotice({ notice, onLeave }: { notice: DialogNotice; onLeave: () => void }) {
  if (notice === "notCompleted") {
    return (
      <p role="status" className="text-sm break-keep text-muted-foreground">
        {PURCHASE_MESSAGES.notCompleted} 다시 결제하거나 다른 결제수단을 고를 수 있어요.
      </p>
    );
  }

  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-lg bg-destructive/10 p-3">
      <p className="text-sm break-keep text-destructive-text">{PURCHASE_MESSAGES[notice]}</p>
      {notice === "sdkUnavailable" && (
        <Button type="button" variant="outline" size="sm" onClick={() => window.location.reload()}>
          새로고침
        </Button>
      )}
      {notice === "failed" && (
        <Link
          to={SUPPORT_DESTINATIONS["inquiry-new"].to}
          onClick={onLeave}
          className="text-sm font-medium text-destructive-text underline underline-offset-4 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
        >
          {SUPPORT_DESTINATIONS["inquiry-new"].label}
        </Link>
      )}
    </div>
  );
}
