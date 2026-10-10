import { z } from "zod";

import { isBankCode, type AdminCreatorPayoutPayeeReplaceRequest } from "@/entities/creator-payout";

const REASON_MAX_LENGTH = 1000;

/** 서버도 공백 사유를 422 로 거부하고 1,000자를 넘으면 거부한다 — 같은 규칙을 먼저 건다. */
const reasonText = z
  .string()
  .refine((value) => value.trim().length > 0, { message: "사유를 입력해주세요." })
  .refine((value) => value.trim().length <= REASON_MAX_LENGTH, { message: "사유는 1,000자까지 쓸 수 있어요." });

export const reasonSchema = z.object({ reasonText });
export type ReasonFormValues = z.infer<typeof reasonSchema>;

/**
 * 이체 기록. 이체일은 신청일(KST)부터 오늘(KST)까지다 — 둘 다 `YYYY-MM-DD` 라 문자열 비교가 날짜 비교다. 범위는 화면이
 * 열린 때 정해지므로 스키마를 그 두 날짜로 만든다(자정을 넘겨 열어 둔 화면은 서버가 422 로 마지막 판정을 한다).
 */
export function createTransferSchema({ requestedOn, today }: { requestedOn: string; today: string }) {
  return z.object({
    transferredOn: z
      .string()
      .refine((value) => /^\d{4}-\d{2}-\d{2}$/.test(value), { message: "이체일을 골라주세요." })
      .refine((value) => value >= requestedOn && value <= today, {
        message: `이체일은 신청일(${requestedOn})부터 오늘(${today})까지만 넣을 수 있어요.`,
      }),
    adminMemo: z.string().refine((value) => value.trim().length <= REASON_MAX_LENGTH, {
      message: "메모는 1,000자까지 쓸 수 있어요.",
    }),
  });
}
export type TransferFormValues = z.infer<ReturnType<typeof createTransferSchema>>;

/** 숫자 칸에 붙여 넣은 하이픈·공백. 화면에서는 받아 주고 보낼 때 뺀다 — 서버는 숫자만 받는다. */
export function stripSeparators(value: string) {
  return value.replace(/[\s-]/g, "");
}

/**
 * 수취 정보 교체. 형식은 서버와 같은 기준이다 — 실명은 앞뒤 공백을 뺀 1~40자, 주민등록번호 숫자 13자리, 계좌번호 숫자
 * 6~20자리, 은행은 목록 안. 외국인등록번호와 생년월일 대조는 서버만 본다. 은행은 고르기 전이 `null` 이다(첫 은행을
 * 기본값으로 두면 고르지 않은 채 잘못된 은행으로 들어간다).
 */
export const replacePayeeSchema = z.object({
  legalName: z
    .string()
    .refine((value) => value.trim().length > 0, { message: "실명을 입력해주세요." })
    .refine((value) => value.trim().length <= 40, { message: "실명은 40자까지 입력할 수 있어요." }),
  rrn: z
    .string()
    .refine((value) => /^[0-9]{13}$/.test(stripSeparators(value)), { message: "주민등록번호 13자리를 입력해주세요." }),
  bankCode: z
    .string()
    .nullable()
    .refine((value) => value !== null && isBankCode(value), { message: "은행을 골라주세요." }),
  accountNumber: z.string().refine((value) => /^[0-9]{6,20}$/.test(stripSeparators(value)), {
    message: "계좌번호를 숫자 6~20자리로 입력해주세요.",
  }),
  reasonText,
});
export type ReplacePayeeFormValues = z.input<typeof replacePayeeSchema>;

export const replacePayeeDefaultValues: ReplacePayeeFormValues = {
  legalName: "",
  rrn: "",
  bankCode: null,
  accountNumber: "",
  reasonText: "",
};

/** 검증을 통과한 값을 요청으로. 실명·사유의 앞뒤 공백과 숫자 칸의 하이픈·공백을 뺀다. 은행은 검증이 목록 안을 보장한다. */
export function replacePayeeFormToServer(
  values: ReplacePayeeFormValues & { bankCode: string },
): AdminCreatorPayoutPayeeReplaceRequest {
  return {
    legalName: values.legalName.trim(),
    rrn: stripSeparators(values.rrn),
    bankCode: values.bankCode,
    accountNumber: stripSeparators(values.accountNumber),
    reasonText: values.reasonText.trim(),
  };
}
