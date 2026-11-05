import { z } from "zod";

import { isBankCode } from "@/entities/creator-payout";

/** 숫자 칸에 붙여 넣은 하이픈·공백. 화면에서는 받아 주고 보낼 때 뺀다(`formToServer`) — 주민등록번호를 `000000-0000000`
 * 으로 적는 것이 자연스럽고, 서버는 숫자만 받는다. */
export function stripSeparators(value: string): string {
  return value.replace(/[\s-]/g, "");
}

/** 지급 정보 입력. 형식 검사는 서버(`parse_payout_info`)와 같은 기준이다 — 실명은 앞뒤 공백을 뺀 1~40자, 주민등록번호는
 * 숫자 13자리, 계좌번호는 숫자 6~20자리, 은행은 목록 안. 어긋나면 화면은 통과시키고 서버가 422 로 거절한다.
 *
 * 은행은 처음에 고른 값이 없어야 해서(첫 항목을 기본값으로 두면 고르지 않은 채 잘못된 은행으로 등록된다) `nullable`
 * 이다. 외국인등록번호·본인인증 생년월일 대조는 서버만 할 수 있어 여기서 보지 않는다. */
export const payoutInfoSchema = z.object({
  legalName: z
    .string()
    .refine((value) => value.trim().length > 0, { message: "실명을 입력해 주세요" })
    .refine((value) => value.trim().length <= 40, { message: "실명은 40자까지 입력할 수 있어요" }),
  rrn: z
    .string()
    .refine((value) => /^[0-9]{13}$/.test(stripSeparators(value)), { message: "주민등록번호 13자리를 입력해 주세요" }),
  bankCode: z
    .string()
    .nullable()
    .refine((value) => value !== null && isBankCode(value), { message: "은행을 선택해 주세요" }),
  accountNumber: z
    .string()
    .refine((value) => /^[0-9]{6,20}$/.test(stripSeparators(value)), {
      message: "계좌번호를 숫자 6~20자리로 입력해 주세요",
    }),
  agreed: z.boolean().refine((value) => value, { message: "동의해야 등록할 수 있어요" }),
});

/** 폼이 쥐는 값(은행은 아직 고르지 않은 `null` 을 담는다)과, 검증을 통과해 넘어오는 값(은행이 목록 안의 코드로 좁혀진다).
 * 은행 검증이 타입 가드라 둘이 갈린다. */
export type PayoutInfoFormValues = z.input<typeof payoutInfoSchema>;
export type PayoutInfoSubmitValues = z.output<typeof payoutInfoSchema>;

/** 이미 등록한 정보가 있어도 칸을 채우지 않는다 — 서버가 원문을 돌려주지 않고(마스킹 값뿐), 바꿀 때는 넷을 모두 새로
 * 받는다. 동의도 입력할 때마다 새로 받는다. */
export const payoutInfoDefaultValues: PayoutInfoFormValues = {
  legalName: "",
  rrn: "",
  bankCode: null,
  accountNumber: "",
  agreed: false,
};
