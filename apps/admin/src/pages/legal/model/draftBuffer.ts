import type { components } from "@ai-character-chat/api-types";

type AdminLegalDraftItem = components["schemas"]["AdminLegalDraftItem"];

/** 편집 화면이 들고 있는 초안 한 벌. 게시는 저장된 초안을 발행하므로, 본문과 변경 안내 둘 다 저장분과 같아야 게시할 수 있다
 * — 하나만 비교하면 저장하지 않은 안내(또는 본문)가 아니라 이전 저장분이 게시된다. */
export type DraftBuffer = {
  bodyMarkdown: string;
  changeNotice: string;
};

export function toDraftBuffer(draft: AdminLegalDraftItem | null | undefined): DraftBuffer {
  return { bodyMarkdown: draft?.bodyMarkdown ?? "", changeNotice: draft?.changeNoticeMarkdown ?? "" };
}

/** 서버에 보낼 안내. 공백뿐이면 `null`(비움) — 서버도 게시할 때 공백뿐인 안내를 없는 것으로 본다. */
export function changeNoticeToServer(notice: string): string | null {
  return notice.trim() === "" ? null : notice;
}

/** 안내는 서버로 보낼 값으로 비교한다 — 공백만 친 칸이 "저장할 변경"으로 남아 저장해도 꺼지지 않는 일이 없게. */
export function isDraftBufferDirty(buffer: DraftBuffer, saved: DraftBuffer): boolean {
  return (
    buffer.bodyMarkdown !== saved.bodyMarkdown ||
    changeNoticeToServer(buffer.changeNotice) !== changeNoticeToServer(saved.changeNotice)
  );
}
