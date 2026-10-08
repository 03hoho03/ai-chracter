import { z } from "zod";

/** 구매 확인 다이얼로그의 폼.
 *
 * 구매자 이름·휴대폰·이메일은 결제대행사가 요구하는 값이라 결제창에 넘길 때만 쓴다. 우리 서버의 주문 요청에는 싣지
 * 않고, 다음 구매를 위해 저장하지도 않는다(매번 입력한다). 이메일은 계정 이메일로 미리 채운다.
 *
 * 휴대폰은 하이픈을 허용하고 숫자만 세어 10~11자리를 본다 — 결제창에는 숫자만 넘긴다(`toPortOneCustomer`).
 * 이메일도 늘 받는다: 결제대행사가 PC 결제에서 요구하고, 계정 이메일로 이미 채워져 있어 모바일에서 따로 빼는 쪽이
 * 기기 판정 하나만 늘린다. */
export const purchaseFormSchema = z.object({
  payMethodKey: z.string().min(1, { message: "결제수단을 골라 주세요" }),
  fullName: z.string().refine((value) => value.trim().length > 0, { message: "이름을 입력해 주세요" }),
  phoneNumber: z
    .string()
    .refine((value) => /^\d{10,11}$/.test(toDigits(value)), { message: "휴대폰 번호를 숫자 10~11자리로 입력해 주세요" }),
  email: z.email({ message: "이메일 형식이 올바르지 않습니다" }),
  agreed: z.boolean().refine((value) => value, { message: "구매 조건에 동의해 주세요" }),
});

export type PurchaseFormValues = z.infer<typeof purchaseFormSchema>;

export function getPurchaseFormDefaultValues(email: string, payMethodKey: string): PurchaseFormValues {
  return { payMethodKey, fullName: "", phoneNumber: "", email, agreed: false };
}

function toDigits(value: string): string {
  return value.replace(/[\s-]/g, "");
}

/** 결제창의 `customer` 로 넘길 모양. 서버로 가는 값이 아니다. */
export function toPortOneCustomer(values: PurchaseFormValues): { fullName: string; phoneNumber: string; email: string } {
  return { fullName: values.fullName.trim(), phoneNumber: toDigits(values.phoneNumber), email: values.email };
}
