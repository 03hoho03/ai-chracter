import type { CharacterDraftContent } from "@/entities/content";

import type { CharacterBuilderFormValues } from "./schema";

/**
 * `GET /contents/{id}/draft` 응답 -> 폼 defaultValues (techspec-overview.md §8.1, 순수 함수).
 *
 * situationalImages는 BE가 이미 `order` 기준으로 정렬해 배열로 내려주므로(`_character_draft_response`),
 * 별도 정렬 없이 응답 배열 순서를 그대로 폼 배열 순서로 복원하는 것만으로 §2의 "order 기준 정렬 후
 * 배열로 복원"을 만족한다 — 서버 스키마 자체에 숫자 order 필드가 없다(formToServer와 대칭).
 *
 * 받는 타입이 `CharacterDraftResponse`가 아니라 id를 뺀 `CharacterDraftContent`인 이유는 US-007이다
 * — 아직 서버에 없는 초안(`createEmptyDraft`)도 같은 함수로 폼 초기값을 만든다.
 */
export function serverToForm(data: CharacterDraftContent): CharacterBuilderFormValues {
  return {
    profile: {
      name: data.name,
      oneLiner: data.oneLiner,
      image: data.thumbnailAssetId ? { assetId: data.thumbnailAssetId } : null,
    },
    intro: {
      firstMessage: data.intro,
      exampleDialogues: data.exampleDialogues,
      playGuide: data.playguide ?? undefined,
    },
    prompt: {
      characterPrompt: data.characterPrompt,
    },
    situationalImages: data.situationalImages.map((image) => ({
      id: image.id,
      image: image.imageAssetId ? { assetId: image.imageAssetId } : null,
      situationDescription: image.triggerCondition,
    })),
    registration: {
      description: data.description,
      genre: data.genreId,
      target: data.target,
      hashtags: data.hashtags,
      visibility: data.visibility,
    },
  };
}
