import type { NotesFormValues } from "./schema";

/** 서버의 노트 글 → 폼의 줄 목록. 줄바꿈마다 한 사실이고, 빈 줄은 버린다. 줄 키는 새로 만든다(서버에 줄 id 가
 * 없다). */
export function serverToForm(settingNotes: string, createId: () => string = () => crypto.randomUUID()): NotesFormValues {
  return {
    notes: settingNotes
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .map((text) => ({ id: createId(), text })),
  };
}
