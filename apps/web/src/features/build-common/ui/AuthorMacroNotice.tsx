import { TriangleAlert } from "lucide-react";

import { findAuthorMacroTypos, hasCharMacro } from "@/shared/lib/text/authorMacroWarnings";

type AuthorMacroNoticeProps = {
  /** 칸의 지금 글. 글이 아닌 값(배열 칸 등)은 호출부가 거른다. */
  text: string;
  contentType: "story" | "character";
};

/**
 * 작가 글 칸에서 이름으로 바뀌지 않을 매크로를 알린다 — 중괄호 겹이 틀린 오타, 그리고 스토리의 `{{char}}`(가리킬 한 사람이
 * 없어 글자 그대로 남는다). 발행은 막지 않는다. 폼 타입에 묶이지 않게 글을 값으로 받아 스토리·캐릭터 빌더가 함께 쓴다.
 * 모양은 이미지 표기 안내(`MediaTagOutsideNotice`)와 같다.
 */
export function AuthorMacroNotice({ text, contentType }: AuthorMacroNoticeProps) {
  const typos = findAuthorMacroTypos(text);
  const hasStoryChar = contentType === "story" && hasCharMacro(text);
  if (typos.length === 0 && !hasStoryChar) return null;

  return (
    <>
      {typos.length > 0 && (
        <p className="flex items-start gap-1.5 text-xs break-keep text-muted-foreground">
          <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
          <span>
            이름으로 바뀌려면 {"{{user}}"}처럼 중괄호를 두 겹으로 써야 해요:{" "}
            <span className="break-all text-foreground">{typos.join(" ")}</span>
          </span>
        </p>
      )}
      {hasStoryChar && (
        <p className="flex items-start gap-1.5 text-xs break-keep text-muted-foreground">
          <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
          <span>
            스토리에서는 <span className="text-foreground">{"{{char}}"}</span>가 이름으로 바뀌지 않고 글자 그대로 보여요.
            인물 이름을 직접 써 주세요.
          </span>
        </p>
      )}
    </>
  );
}
