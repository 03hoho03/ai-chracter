import { z } from "zod";

import { hasNovelErrorCode, toNovelActionError, type NovelAction, type NovelActionErrorNotice } from "@/entities/novel";
import { isApiError } from "@/shared/api/client";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

/** 서버가 세는 방식의 글자 수 — 앞뒤 공백을 걷은 뒤 코드 포인트 수. */
export function countCharacterChars(value: string): number {
  return Array.from(value.trim()).length;
}

/** 인물 이름(별칭 하나도 같은 규칙). 서버는 앞뒤 공백을 걷고 빈 이름을 받지 않는다. */
export function createCharacterNameSchema(maxLength: number) {
  return z.object({
    name: z
      .string()
      .refine((value) => countCharacterChars(value) > 0, "이름을 입력해주세요")
      .refine((value) => countCharacterChars(value) <= maxLength, `이름은 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`),
  });
}

export type CharacterNameFormValues = z.infer<ReturnType<typeof createCharacterNameSchema>>;

/** 인물 메모. 비워서 저장하면 지운다 — 메모가 빈 인물은 다음 묶음 생성 입력에서 빠진다. */
export function createCharacterMemoSchema(maxLength: number) {
  return z.object({
    memo: z
      .string()
      .refine((value) => countCharacterChars(value) <= maxLength, `메모는 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`),
  });
}

export type CharacterMemoFormValues = z.infer<ReturnType<typeof createCharacterMemoSchema>>;

/**
 * 별칭 하나를 더한 목록. 앞뒤 공백을 걷고, 이미 있는 이름(카드 이름·다른 별칭)이면 더하지 않는다 — 서버도 같은 카드
 * 안 중복을 의미 없는 변경으로 본다. 더할 수 없으면(빈 값·중복·상한) `error` 로 그 이유를 돌려준다.
 */
export function addAlias(
  aliases: readonly string[],
  name: string,
  alias: string,
  maxCount: number,
): { aliases: string[] } | { error: string } {
  const trimmed = alias.trim();
  if (trimmed === "") return { error: "별칭을 입력해주세요" };
  if (trimmed === name || aliases.includes(trimmed)) return { error: `‘${trimmed}’${koreanParticle(trimmed, "은/는")} 이미 이 인물의 이름이에요` };
  if (aliases.length >= maxCount) return { error: `별칭은 ${maxCount}개까지 둘 수 있어요` };
  return { aliases: [...aliases, trimmed] };
}

function takenNameOf(error: unknown): string | undefined {
  if (!isApiError(error) || !error.detail || typeof error.detail !== "object" || !("name" in error.detail)) return undefined;
  const { name } = error.detail;
  return typeof name === "string" ? name : undefined;
}

/** 인물 저장 실패의 문장. 이름·별칭이 다른 카드와 겹치면 서버가 겹친 값을 함께 주므로 그 이름으로 말한다 — 어느
 * 이름이 걸렸는지 알아야 합치기를 고를지 이름을 바꿀지 정할 수 있다. 그 밖은 소설 공통 문장이다. */
export function toCharacterSaveError(error: unknown, action: NovelAction): NovelActionErrorNotice | null {
  if (hasNovelErrorCode(error, "NOVEL_CHARACTER_NAME_TAKEN")) {
    const taken = takenNameOf(error);
    if (taken !== undefined) {
      return {
        message: `‘${taken}’${koreanParticle(taken, "은/는")} 다른 인물이 쓰고 있어요. 같은 인물이면 ‘다른 인물과 합치기’를 써주세요.`,
        shouldRefetchNovel: false,
      };
    }
  }
  return toNovelActionError(error, action);
}
