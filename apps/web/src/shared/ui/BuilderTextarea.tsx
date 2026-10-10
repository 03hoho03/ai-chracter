import type { ComponentProps } from "react";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";

type BuilderTextareaProps = Omit<ComponentProps<typeof Textarea>, "rows"> & {
  rows: number;
};

/**
 * 빌더와 소설 편집 보드의 여러 줄 입력칸 전용 textarea. 높이는 `rows` 하나가 정하고, 내용을 따라
 * 자라지도 손잡이로 끌리지도 않으며, 넘치는 글은 칸 안에서 스크롤된다. 칸이 글만큼 자라면
 * 입력하는 동안 칸 아래 글자 수·도움말·다음 칸이 계속 밀려 내려가고, 수천 자 프롬프트 칸 하나가
 * 화면 몇 배 높이로 자라 폼을 덮는다. 높이를 정하는 자리가 `rows` 하나뿐이어야 하므로 필수로 받고, 호출부에
 * `min-h-*` 를 함께 적지 않는다. 채팅 입력·댓글처럼 글만큼 자라는 것이 의도인 칸은 이 래퍼가
 * 아니라 프리미티브를 그대로 쓴다.
 */
export function BuilderTextarea({ className, ...props }: BuilderTextareaProps) {
  return <Textarea className={cn("field-sizing-fixed resize-none", className)} {...props} />;
}
