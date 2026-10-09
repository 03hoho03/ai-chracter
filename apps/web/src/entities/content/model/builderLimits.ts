import builderLimits from "@api-contract/content/builder_limits.json";
import { z } from "zod";

import { countCharacters } from "@/shared/lib/text/characterCount";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

/**
 * 빌더의 글자 수·개수 한도. 서버가 초안 저장과 발행에서 같은 표로 검사하므로(넘으면 422) 숫자를 여기 다시 적지 않고
 * 그 파일을 읽는다 — 한쪽만 고쳐 화면은 받는 글을 서버가 거절하는 일을 막는다. 글자 수는 코드 포인트, 앞뒤 공백을
 * 지우지 않고 센다(`shared/lib/text/characterCount`).
 */
const { common, character, story } = builderLimits;

export const MAX_NAME_LENGTH = common.nameMaxLength;
export const MAX_ONE_LINER_LENGTH = common.oneLinerMaxLength;
export const MAX_DESCRIPTION_LENGTH = common.descriptionMaxLength;
export const MAX_HASHTAGS = common.hashtagMaxCount;
export const MAX_HASHTAG_LENGTH = common.hashtagMaxLength;

export const MAX_INTRO_LENGTH = character.introMaxLength;
export const MAX_CHARACTER_PROMPT_LENGTH = character.characterPromptMaxLength;
export const MAX_PLAY_GUIDE_LENGTH = character.playguideMaxLength;
export const MAX_EXAMPLE_DIALOGUE_LINE_LENGTH = character.exampleDialogueLineMaxLength;
export const MAX_EXAMPLE_DIALOGUES = character.exampleDialogueMaxCount;
export const MAX_SITUATIONAL_IMAGE_TRIGGER_LENGTH = character.situationalImageTriggerMaxLength;

export const MAX_STARTING_SETUPS = story.startingSetupMaxCount;
export const MAX_SUGGESTED_REPLIES = story.suggestedReplyMaxCount;
export const MAX_DEVELOPMENT_EXAMPLES = story.developmentExampleMaxCount;

/**
 * 서버가 저장 본문을 한도 검사에서 거절한(422) 경우의 안내. 같은 값으로는 몇 번을 다시 보내도 거절되므로 기다리라고
 * 하지 않고 줄이라고 말한다. 422 본문에서는 어느 항목이 넘쳤는지 화면이 가려낼 수 없어(필드 오류가 이름만 남고
 * 위치는 버려진다) 항목을 짚지 않는다. 두 빌더가 같은 문장을 쓴다.
 */
export const BUILDER_SAVE_LIMIT_MESSAGE =
  "글자 수나 개수 제한을 넘은 항목이 있어 저장하지 못했어요. 입력한 내용은 그대로 있으니 긴 글이나 많이 추가한 항목을 줄여주세요.";

/** 글자 수 상한을 넘었을 때의 발행 검사 문구. 라벨 끝 글자에 맞춰 조사를 고른다. */
export function characterLimitMessage(label: string, max: number): string {
  return `${label}${koreanParticle(label, "은/는")} ${max}자 이하로 입력해주세요`;
}

/**
 * 글자 수 상한 검사 — `z.string().refine(...characterLimit(max, label))` 처럼 펼쳐 넣는다. zod 의 `.max()` 는 UTF-16
 * 단위라 이모지를 두 글자로 세어 서버가 받는 글을 막으므로 코드 포인트로 다시 센다.
 */
export function characterLimit(max: number, label: string) {
  return [(value: string) => countCharacters(value) <= max, characterLimitMessage(label, max)] as const;
}

export const HASHTAG_LIMIT_MESSAGE = `해시태그는 최대 ${MAX_HASHTAGS}개예요. 더 넣으려면 하나를 지워 주세요.`;
export const HASHTAG_TOO_LONG_MESSAGE = characterLimitMessage("해시태그", MAX_HASHTAG_LENGTH);

/**
 * 두 빌더가 함께 쓰는 해시태그 목록 검사. 위반을 원소가 아니라 목록 자리에 싣는다 — 화면은 칩 목록 아래 한 줄로만
 * 오류를 보여 준다. 새로 넣는 태그는 입력 단계에서 이미 걸러지므로, 이 검사는 다른 경로로 들어온 값을 발행 전에 막는다.
 */
export const hashtagsSchema = z
  .array(z.string())
  .superRefine((tags, ctx) => {
    if (tags.length > MAX_HASHTAGS) ctx.addIssue({ code: "custom", message: HASHTAG_LIMIT_MESSAGE });
    else if (tags.some((tag) => countCharacters(tag) > MAX_HASHTAG_LENGTH)) {
      ctx.addIssue({ code: "custom", message: HASHTAG_TOO_LONG_MESSAGE });
    }
  })
  .default([]);
