import type { PreviewSessionState } from "@/entities/preview-session";

const EMPTY_HINT: Record<PreviewSessionState["contentType"], string> = {
  character: "인트로를 쓰면 여기에 첫 메시지로 보여요. 메시지를 보내면 저장하지 않은 지금 내용 그대로 대화해 볼 수 있어요.",
  story:
    "첫 번째 시작설정의 시작상황이 여기에 첫 메시지로 보여요. 메시지를 보내면 저장하지 않은 지금 내용 그대로 대화해 볼 수 있어요.",
};

/**
 * 미리보기 대화에 보이는 글이 하나도 없을 때 그 자리에 둘 안내. 보이는 글이 있으면 `undefined`.
 *
 * 메시지가 0개일 때만이 아니다 — 캐릭터는 인트로가 비어도, 스토리는 첫 시작설정의 시작상황·프롤로그가 다 비어도 내용이 빈
 * 첫 메시지 하나가 들어온다. 그래서 "내용이 공백이 아닌 메시지가 없다"로 판정한다. 시작설정이 없어도 서버는 세션을 열므로
 * 안내는 무엇을 써야 보낼 수 있다고 말하지 않는다.
 */
export function previewEmptyHint(
  contentType: PreviewSessionState["contentType"],
  messages: readonly { content: string }[],
): string | undefined {
  if (messages.some((message) => message.content.trim().length > 0)) return undefined;
  return EMPTY_HINT[contentType];
}
