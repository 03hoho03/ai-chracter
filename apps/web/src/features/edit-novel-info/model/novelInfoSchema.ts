import { z } from "zod";

/** 서버가 세는 방식의 글자 수 — 앞뒤 공백을 걷은 뒤 코드 포인트 수. `.length` 는 이모지를 2자로 센다. */
export function countInfoChars(value: string): number {
  return Array.from(value.trim()).length;
}

/** 소설 제목 폼. 서버는 빈 제목을 받지 않는다(제목은 지울 수 없고 바꾸기만 한다) — 공백만 쓴 제목도 서버가 앞뒤를
 * 걷어 빈 값이 되므로 여기서 같이 막는다. 상한은 상세의 `limits` 에서만 읽는다. */
export function createTitleFormSchema(maxLength: number) {
  return z.object({
    title: z
      .string()
      .refine((value) => countInfoChars(value) > 0, "제목을 입력해주세요")
      .refine((value) => countInfoChars(value) <= maxLength, `제목은 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`),
  });
}

export type TitleFormValues = z.infer<ReturnType<typeof createTitleFormSchema>>;

/** 소개 폼. 비워서 저장하면 소개를 지운다(서버가 빈 글을 받는다). */
export function createSynopsisFormSchema(maxLength: number) {
  return z.object({
    synopsis: z
      .string()
      .refine((value) => countInfoChars(value) <= maxLength, `소개는 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`),
  });
}

export type SynopsisFormValues = z.infer<ReturnType<typeof createSynopsisFormSchema>>;
