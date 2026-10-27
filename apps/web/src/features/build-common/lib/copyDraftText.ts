import { toast } from "sonner";

import { DraftTextModal } from "../ui/DraftTextModal";

/**
 * 저장이 실패하거나 연결이 끊긴 동안 쓴 글을 클립보드에 넣는다. 넣지 못하면(권한 거부, 클립보드가 없는 비보안 연결) 글을 골라 둔
 * 창을 대신 연다 — 저장되지 않은 글을 가져갈 길이 이것뿐이라 "복사하지 못했어요"로 끝내지 않는다. 버튼 클릭에서 부르므로 던지지
 * 않는다.
 */
export async function copyDraftText(text: string): Promise<void> {
  if (text === "") {
    toast("아직 복사할 글이 없어요.");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    toast.success("작성한 글을 복사했어요. 메모장 같은 곳에 붙여 두세요.");
  } catch {
    void DraftTextModal.call({ text });
  }
}
