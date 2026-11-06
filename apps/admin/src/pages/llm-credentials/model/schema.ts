import { z } from "zod";

import type {
  AdminLlmCredential,
  AdminLlmCredentialCreateRequest,
  AdminLlmCredentialSecretRequest,
  AdminLlmCredentialUpdateRequest,
} from "./credential";
import type { CredentialFormField } from "./failure";

/**
 * 자격 폼 넷(추가·키 교체·이름 수정·충전액)과 삭제 확인. 서버가 같은 값을 422 로 거절하므로 서버와 같은 규칙을 먼저 건다 — 이름은
 * 앞뒤 공백을 뺀 1~40자(코드 포인트로 센다 — 서버가 그렇게 센다)에 NUL 없음, 키는 앞뒤 공백을 뺀 인쇄 가능한 ASCII 20~256자,
 * 충전액은 0보다 큰 달러 금액으로 정수 부분 10자리·소수 둘째 자리까지, 임계는 1~99 정수다.
 *
 * 숫자 칸도 문자열로 받는다 — 숫자 입력의 빈 칸은 `NaN` 이 되어 "선택 칸 비움"과 "잘못된 값"이 갈리지 않는다. 충전액은 검증한 달러
 * 문자열을 그대로 보낸다 — 서버도 충전액을 달러 문자열로 주고받고 마이크로달러 변환은 서버 안에만 있어, 화면이 수로 바꿔 셈할 일이 없다.
 */

const LABEL_MAX_LENGTH = 40;
const CREDIT_INTEGER_MAX_DIGITS = 10;
const API_KEY_SHAPE = /^[\x21-\x7e]{20,256}$/;
const DOLLAR_SHAPE = /^\d+(\.\d{1,2})?$/;
const INTEGER_SHAPE = /^\d+$/;

const LABEL_FORMAT_TEXT = "이름은 앞뒤 공백을 뺀 1~40자예요.";
const API_KEY_FORMAT_TEXT = "키 형식이 아니에요. 공백·줄바꿈 없이 20~256자여야 해요.";
const CREDIT_FORMAT_TEXT = "달러 금액을 소수 둘째 자리까지 넣어 주세요(예: 50 또는 49.5).";
const ALERT_FORMAT_TEXT = "1~99 사이 정수로 넣어 주세요.";

/** 서버 검증 목록이 칸을 거절했을 때 그 칸에 다는 문장. 서버는 입력값도 사유 원문(영어)도 화면용으로 주지 않아 칸의 규칙을 다시 말한다. */
export const SERVER_FIELD_REJECTION_TEXTS = {
  label: LABEL_FORMAT_TEXT,
  apiKey: API_KEY_FORMAT_TEXT,
  creditUsd: CREDIT_FORMAT_TEXT,
  alertPct: ALERT_FORMAT_TEXT,
} as const satisfies Record<CredentialFormField, string>;

const labelField = z
  .string()
  .refine((value) => value.trim().length > 0, { message: "이름을 입력해 주세요." })
  .refine((value) => Array.from(value.trim()).length <= LABEL_MAX_LENGTH, { message: "이름은 40자까지예요." })
  .refine((value) => !value.includes("\0"), { message: "이름에 쓸 수 없는 글자가 있어요." });

const apiKeyField = z
  .string()
  .refine((value) => value.trim().length > 0, { message: "키를 붙여넣어 주세요." })
  .refine((value) => API_KEY_SHAPE.test(value.trim()), { message: API_KEY_FORMAT_TEXT });

const alertPctField = z.string().refine(
  (value) => {
    const trimmed = value.trim();
    return INTEGER_SHAPE.test(trimmed) && Number(trimmed) >= 1 && Number(trimmed) <= 99;
  },
  { message: ALERT_FORMAT_TEXT },
);

/** 추가에서는 충전액이 선택이다 — 비우면 사용액을 세지 않는다. */
const optionalCreditField = z.string().superRefine((value, ctx) => {
  const issue = value.trim() === "" ? undefined : dollarIssue(value.trim());
  if (issue !== undefined) ctx.addIssue({ code: "custom", message: issue });
});

export const addCredentialSchema = z.object({
  apiKey: apiKeyField,
  label: labelField,
  creditUsd: optionalCreditField,
  alertPct: alertPctField,
});
export type AddCredentialFormValues = z.infer<typeof addCredentialSchema>;

/** 키 칸은 서버 값으로 채우지 않는다 — 서버도 키 원문을 돌려주지 않는다. 임계 20 은 서버의 기본값과 같다. */
export const ADD_CREDENTIAL_DEFAULT_VALUES: AddCredentialFormValues = {
  apiKey: "",
  label: "",
  creditUsd: "",
  alertPct: "20",
};

export const replaceSecretSchema = z.object({ apiKey: apiKeyField });
export type ReplaceSecretFormValues = z.infer<typeof replaceSecretSchema>;
export const REPLACE_SECRET_DEFAULT_VALUES: ReplaceSecretFormValues = { apiKey: "" };

/** 이름·임계 수정. 충전액 칸을 싣지 않는다 — 이 폼은 사용액 기준을 건드릴 수 없다. */
export const editCredentialSchema = z.object({ label: labelField, alertPct: alertPctField });
export type EditCredentialFormValues = z.infer<typeof editCredentialSchema>;

/** 충전액 맞추기. 여기서는 값이 있어야 한다(지우기는 따로 있다). */
export const creditBasisSchema = z.object({
  creditUsd: z.string().superRefine((value, ctx) => {
    const issue = value.trim() === "" ? "충전액을 넣어 주세요." : dollarIssue(value.trim());
    if (issue !== undefined) ctx.addIssue({ code: "custom", message: issue });
  }),
});
export type CreditBasisFormValues = z.infer<typeof creditBasisSchema>;

/** 지우기는 되돌릴 수 없어 이름을 정확히 다시 쳐야 한다. 앞뒤 공백만 봐준다. */
export function createDeleteConfirmSchema(label: string) {
  return z.object({
    confirmText: z.string().refine((value) => value.trim() === label, { message: "이름이 정확히 같아야 지울 수 있어요." }),
  });
}
export type DeleteConfirmFormValues = z.infer<ReturnType<typeof createDeleteConfirmSchema>>;

export function addFormToServer(values: AddCredentialFormValues): AdminLlmCredentialCreateRequest {
  const creditUsd = values.creditUsd.trim();
  return {
    provider: "anthropic",
    label: values.label.trim(),
    apiKey: values.apiKey.trim(),
    creditUsd: creditUsd === "" ? null : creditUsd,
    alertPct: Number(values.alertPct.trim()),
  };
}

export function replaceFormToServer(values: ReplaceSecretFormValues): AdminLlmCredentialSecretRequest {
  return { apiKey: values.apiKey.trim() };
}

/** 충전액 칸 자체를 싣지 않아 서버가 충전액·기준 시각을 건드리지 않는다. 기준 다시 잡기는 생성 타입에서 필수라 늘 적는다. */
export function editFormToServer(values: EditCredentialFormValues): AdminLlmCredentialUpdateRequest {
  return { label: values.label.trim(), alertPct: Number(values.alertPct.trim()), resetCreditBasis: false };
}

export function editServerToForm(credential: AdminLlmCredential): EditCredentialFormValues {
  return { label: credential.label, alertPct: String(credential.alertPct) };
}

/** 늘 기준을 다시 잡는다 — 값이 바뀌면 서버가 어차피 다시 잡고, 같으면 이 플래그가 다시 잡는다. 운영자의 일("콘솔 잔액을 보고
 * 맞춘다")이 두 경우를 가르지 않는다. */
export function creditBasisToServer(values: CreditBasisFormValues): AdminLlmCredentialUpdateRequest {
  return { creditUsd: values.creditUsd.trim(), resetCreditBasis: true };
}

export function clearCreditToServer(): AdminLlmCredentialUpdateRequest {
  return { creditUsd: null, resetCreditBasis: false };
}

export function creditServerToForm(credential: AdminLlmCredential): CreditBasisFormValues {
  return { creditUsd: credential.creditUsd ?? "" };
}

/** 값이 있을 때의 달러 금액 규칙에서 처음 걸리는 것. 정수 부분 자릿수는 앞자리 0 을 빼고 센다 — 서버는 수로 읽어 앞자리 0 을 세지 않는다. */
function dollarIssue(value: string): string | undefined {
  if (!DOLLAR_SHAPE.test(value)) return CREDIT_FORMAT_TEXT;
  const [integerPart = ""] = value.split(".");
  if (integerPart.replace(/^0+(?=\d)/, "").length > CREDIT_INTEGER_MAX_DIGITS) return "충전액은 정수 부분 10자리까지예요.";
  if (!(Number(value) > 0)) return "0보다 커야 해요.";
  return undefined;
}
