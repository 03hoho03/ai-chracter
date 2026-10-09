import { z } from "zod";

/** 서버가 세는 방식의 글자 수 — 앞뒤 공백을 걷은 뒤 코드 포인트 수. `.length` 는 이모지를 2자로 센다. */
function countChars(value: string): number {
  return Array.from(value.trim()).length;
}

/** 버전 이름 폼. 서버는 앞뒤 공백을 걷고 빈 이름을 받지 않는다. 상한은 상세의 `limits.snapshotNameMaxLength` 에서만
 * 읽는다. */
export function createSnapshotNameSchema(maxLength: number) {
  return z.object({
    name: z
      .string()
      .refine((value) => countChars(value) > 0, "버전 이름을 입력해주세요")
      .refine((value) => countChars(value) <= maxLength, `이름은 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`),
  });
}

export type SnapshotNameFormValues = z.infer<ReturnType<typeof createSnapshotNameSchema>>;

/** 저장 모달을 열 때 채워 둘 이름. 지금 어디까지 있는지가 가장 흔한 이름이라 마지막 화 번호로 짓는다. 화가 없으면
 * 아직 소설이 시작되기 전이다. */
export function toDefaultSnapshotName(chapterOrdinals: readonly number[]): string {
  if (chapterOrdinals.length === 0) return "첫 화 전";
  return `${Math.max(...chapterOrdinals)}화까지`;
}
