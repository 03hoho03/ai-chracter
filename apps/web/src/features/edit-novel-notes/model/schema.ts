import { zodResolver } from "@hookform/resolvers/zod";
import type { UseFormProps } from "react-hook-form";
import { z } from "zod";

import { formToServer } from "./formToServer";

/** 서버가 세는 방식의 글자 수 — 앞뒤 공백을 걷은 뒤 코드 포인트 수. `.length` 는 이모지를 2자로 센다. */
export function countNotesChars(value: string): number {
  return Array.from(value.trim()).length;
}

const noteItemSchema = z.object({
  /** 화면에서 줄을 가르는 키(`useFieldArray` 의 key). 서버로 가지 않는다. */
  id: z.string(),
  text: z.string(),
});

/** 설정 노트 폼 — 짧은 사실을 한 줄씩. 서버는 노트를 글 하나로 받으므로(상한 하나) 상한은 줄마다가 아니라 서버로
 * 보낼 글 전체에 건다. 상한은 상세의 `limits` 에서만 읽는다. 빈 줄은 저장할 때 빠지므로 막지 않는다. */
export function createNotesFormSchema(maxLength: number) {
  return z
    .object({ notes: z.array(noteItemSchema) })
    .superRefine((values, context) => {
      if (countNotesChars(formToServer(values).settingNotes) <= maxLength) return;
      context.addIssue({
        code: "custom",
        path: ["notes"],
        message: `설정 노트는 모두 합쳐 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`,
      });
    });
}

export type NotesFormValues = z.infer<ReturnType<typeof createNotesFormSchema>>;

export function notesFormOptions(maxLength: number): Pick<UseFormProps<NotesFormValues>, "resolver"> {
  return { resolver: zodResolver(createNotesFormSchema(maxLength)) };
}
