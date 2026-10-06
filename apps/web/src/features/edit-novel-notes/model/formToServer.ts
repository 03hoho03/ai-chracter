import type { components } from "@ai-character-chat/api-types";

type NotesRequest = components["schemas"]["NovelSettingNotesRequest"];

/** 폼값 → `PUT /novels/{id}/notes`. 서버는 노트를 글 하나로 받으므로 줄마다 앞뒤 공백을 걷고 빈 줄을 버린 뒤 줄바꿈
 * 하나로 잇는다. 모든 줄이 비면 빈 노트다. */
export function formToServer(values: { notes: { text: string }[] }): NotesRequest {
  return {
    settingNotes: values.notes
      .map((note) => note.text.trim())
      .filter((text) => text.length > 0)
      .join("\n"),
  };
}
