import type { NovelChapterUpdateRequest } from "@/entities/novel";

import type { AuthorNoteFormValues, EpisodeTitleFormValues } from "./episodeSchema";

// 서버는 보낸 칸만 고치므로 폼마다 자기 칸 하나만 싣는다. 스키마는 공백을 걷은 값으로 검사만 하고 값은 그대로 두므로,
// 앞뒤 공백은 여기서 걷는다.

/** 화 제목 폼값 → `PATCH /novels/{id}/chapters/{chapterId}` 본문. 제목 비우기(`null`)는 폼 제출이 아니라 따로 보낸다. */
export function episodeTitleFormToServer(values: EpisodeTitleFormValues): NovelChapterUpdateRequest {
  return { title: values.title.trim() };
}

/** 작가의 말 폼값 → 같은 엔드포인트 본문. 공백만 남으면 빈 글이 되어 작가의 말을 지운다. */
export function authorNoteFormToServer(values: AuthorNoteFormValues): NovelChapterUpdateRequest {
  return { authorNote: values.authorNote.trim() };
}
