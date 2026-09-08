import { z } from "zod";

import type { ModerationActionType } from "@/entities/report";

export type ProcessAction = Extract<ModerationActionType, "restrict" | "delete" | "reject">;

export const PROCESS_OPTIONS: { value: ProcessAction; label: string }[] = [
  { value: "restrict", label: "이용제한 부과" },
  { value: "delete", label: "삭제" },
  { value: "reject", label: "조치 없음(반려)" },
];

/** 화면이 실제로 그리는 목록을 스키마의 근거로 삼아 옵션과 검증이 어긋날 수 없게 한다. */
export const PROCESS_ACTION_VALUES = PROCESS_OPTIONS.map((option) => option.value);

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
