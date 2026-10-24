import type { components } from "@ai-character-chat/api-types";
import { z } from "zod";

import { isApiError } from "@/shared/lib/api/client";

export type AdminPromptDraftChangesResponse = components["schemas"]["AdminPromptDraftChangesResponse"];
export type AdminPromptSectionChange = components["schemas"]["AdminPromptSectionChange"];
export type AdminPromptSectionSemver = components["schemas"]["AdminPromptSectionSemver"];

/** 섹션 판 단계. 게시 요청의 `levels` 값 타입에서 뽑아, 서버가 단계를 늘리면 아래 라벨이 컴파일 오류로 잡힌다. */
export type SemverLevel = NonNullable<components["schemas"]["AdminPromptPublishRequest"]["levels"]>[string];

/** 운영자가 판 문자열에서 보는 말 그대로 둔다. 순서가 곧 화면의 버튼 순서다(큰 단계부터). */
export const SEMVER_LEVEL_LABELS = {
  major: "major",
  minor: "minor",
  patch: "patch",
} satisfies Record<SemverLevel, string>;

export function isSemverLevel(value: string): value is SemverLevel {
  return value in SEMVER_LEVEL_LABELS;
}

export const SEMVER_LEVELS = Object.keys(SEMVER_LEVEL_LABELS).filter(isSemverLevel);

export const DEFAULT_SEMVER_LEVEL: SemverLevel = "patch";

type SectionChangeKind = AdminPromptSectionChange["change"];

export const SECTION_CHANGE_LABELS = {
  changed: "바뀜",
  added: "추가",
  removed: "삭제",
  unchanged: "그대로",
  initial: "첫 판",
} satisfies Record<SectionChangeKind, string>;

const semverConflictSchema = z.object({
  rule: z.enum(["semver-draft-changed", "semver-base-moved", "semver-level-for-unchanged-section"]),
  message: z.string(),
});

/** 게시가 "단계를 고른 뒤 바뀐 섹션이 달라졌다"로 거부됐으면 서버 문장을 돌려준다(아니면 null). 409 두 가지(초안이 바뀜·다른
 * 게시가 먼저 들어옴)와, 화면이 낡은 목록으로 골라 바뀌지 않은 섹션에 단계를 보낸 422 가 같은 처리다 — 모달을 닫지 않고 바뀐
 * 섹션을 다시 받아 다시 고르게 한다. */
export function semverConflictMessage(error: unknown): string | null {
  if (!isApiError(error) || (error.status !== 409 && error.status !== 422)) return null;
  const parsed = semverConflictSchema.safeParse(error.detail);
  return parsed.success ? parsed.data.message : null;
}

const ruleDetailSchema = z.object({ rule: z.string(), message: z.string() });

/** `{rule, message}` 꼴 거부의 서버 문장. 그 꼴이 아니면 null. */
export function ruleDetail(error: unknown): { rule: string; message: string } | null {
  if (!isApiError(error)) return null;
  const parsed = ruleDetailSchema.safeParse(error.detail);
  return parsed.success ? parsed.data : null;
}
