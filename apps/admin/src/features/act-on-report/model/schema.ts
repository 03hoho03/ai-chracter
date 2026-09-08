import { z } from "zod";

import type { ModerationActionType } from "@/entities/report";

export type ProcessAction = Extract<ModerationActionType, "restrict" | "delete" | "reject">;

export const PROCESS_LABELS: Record<ProcessAction, string> = {
  restrict: "이용제한 부과",
  delete: "삭제",
  reject: "조치 없음(반려)",
};

export function isProcessAction(value: string): value is ProcessAction {
  return value in PROCESS_LABELS;
}

/** `ProcessAction`에 멤버가 늘면 `PROCESS_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을
 * 손으로 또 적으면 바로 위 `Extract<...>`의 리터럴을 두 번 적는 셈이라 둘이 갈릴 수 있다. */
export const PROCESS_ACTION_VALUES = Object.keys(PROCESS_LABELS).filter(isProcessAction);

export const PROCESS_OPTIONS = PROCESS_ACTION_VALUES.map((value) => ({
  value,
  label: PROCESS_LABELS[value],
}));

/** `adminComment`는 서버가 `str | None`이라 빈 문자열도 받지만, 빈 코멘트를 저장하지 않도록
 * 제출 직전에 트림해 비었으면 `undefined`로 떨군다(호출부의 `?? undefined` 대신 여기서 진다). */
export const reportActionSchema = z.object({
  action: z.enum(PROCESS_ACTION_VALUES, { message: "처리 방법을 선택해주세요" }),
  adminComment: z.string().trim(),
});

export type ReportActionFormValues = z.infer<typeof reportActionSchema>;

/** 되돌릴 수 없는 삭제라 콘텐츠명 완전 일치를 요구한다(`apps/admin/CLAUDE.md`). 기준값이 prop이라
 * 스키마를 팩토리로 만들고 호출부가 `useMemo`로 고정한다. */
export function createDeleteConfirmSchema(contentName: string) {
  return z.object({
    confirmText: z.string().refine((value) => value.trim() === contentName, {
      message: "콘텐츠명이 정확히 일치해야 삭제할 수 있어요",
    }),
  });
}

export type DeleteConfirmFormValues = z.infer<ReturnType<typeof createDeleteConfirmSchema>>;
