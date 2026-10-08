import { z } from "zod";

/** 서버가 세는 방식의 글자 수 — 앞뒤 공백을 걷은 뒤 코드 포인트 수. `.length` 는 이모지를 2자로 센다. */
export function countEpisodeChars(value: string): number {
  return Array.from(value.trim()).length;
}

/** 화 제목 폼. 서버는 빈 제목을 받지 않는다 — 제목을 비우려면 저장이 아니라 "제목 비우기"(`null`)를 쓴다. 상한은
 * 상세의 `limits.chapterTitleMaxLength` 에서만 읽는다. */
export function createEpisodeTitleSchema(maxLength: number) {
  return z.object({
    title: z
      .string()
      .refine((value) => countEpisodeChars(value) > 0, "제목을 입력해주세요. 비우려면 ‘제목 비우기’를 눌러주세요")
      .refine((value) => countEpisodeChars(value) <= maxLength, `제목은 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`),
  });
}

export type EpisodeTitleFormValues = z.infer<ReturnType<typeof createEpisodeTitleSchema>>;

/** 작가의 말 폼. 비워서 저장하면 작가의 말을 지운다(서버가 빈 글을 받는다). */
export function createAuthorNoteSchema(maxLength: number) {
  return z.object({
    authorNote: z
      .string()
      .refine((value) => countEpisodeChars(value) <= maxLength, `작가의 말은 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`),
  });
}

export type AuthorNoteFormValues = z.infer<ReturnType<typeof createAuthorNoteSchema>>;

/** 화 머리의 제목 줄. 제목이 없으면 번호만이다. */
export function toEpisodeHeading(chapter: { ordinal: number; title: string | null }): string {
  return chapter.title === null ? `${chapter.ordinal}화` : `${chapter.ordinal}화. ${chapter.title}`;
}
