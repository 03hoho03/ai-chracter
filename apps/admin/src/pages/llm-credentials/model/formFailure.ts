import type { CredentialFailure, CredentialFormField } from "./failure";
import { SERVER_FIELD_REJECTION_TEXTS } from "./schema";

/** 폼이 할 일로 옮긴 실패 — 어느 칸에 무슨 오류를 달고, 칸에 못 붙는 것은 폼 머리(대화상자 안 실패 문단)에 둔다. */
export type FormFailurePlan<Field extends CredentialFormField> = {
  fieldErrors: { field: Field; message: string }[];
  rootMessage: string | undefined;
  /** 키 칸을 비운다. 붙여넣은 키가 거절됐거나, 결과를 받지 못해 이미 저장됐을 수 있을 때다 — 보내기 직전에 오프라인이었던 실패(보내지
   * 않음)·Anthropic 일시 장애처럼 키가 틀린 게 아닌 실패는 비우지 않아 다시 누르기만 하면 된다. */
  clearsSecret: boolean;
};

export function planFormFailure<Field extends CredentialFormField>(
  failure: CredentialFailure,
  fields: readonly Field[],
): FormFailurePlan<Field> {
  const hasSecret = fields.some((field) => field === "apiKey");
  switch (failure.kind) {
    case "secret-rejected": {
      const secretField = fields.find((field) => field === "apiKey");
      return secretField === undefined
        ? { fieldErrors: [], rootMessage: failure.message, clearsSecret: false }
        : { fieldErrors: [{ field: secretField, message: failure.message }], rootMessage: undefined, clearsSecret: true };
    }
    case "fields": {
      const rejected = fields.filter((field) => failure.fields.some((name) => name === field));
      if (rejected.length === 0) return { fieldErrors: [], rootMessage: failure.message, clearsSecret: false };
      return {
        fieldErrors: rejected.map((field) => ({ field, message: SERVER_FIELD_REJECTION_TEXTS[field] })),
        rootMessage: undefined,
        clearsSecret: rejected.some((field) => field === "apiKey"),
      };
    }
    case "unknown-outcome":
      return { fieldErrors: [], rootMessage: failure.message, clearsSecret: hasSecret };
    case "store-missing":
    case "upstream-unavailable":
    case "stale-order":
    case "pool-uncovered":
    case "enable-blocked":
    case "secret-unreadable":
    case "rate-limited":
    case "not-found":
    case "conflict":
    case "offline":
    case "other":
      return { fieldErrors: [], rootMessage: failure.message, clearsSecret: false };
    default:
      return assertNever(failure);
  }
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 실패: ${JSON.stringify(value)}`);
}
