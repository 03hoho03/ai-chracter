import type { ComponentProps } from "react";
import type { Components, ExtraProps } from "react-markdown";
import Markdown from "react-markdown";

import { cn } from "@ai-character-chat/ui/lib/utils";

import { GUIDE_MARKDOWN_OPTIONS } from "../config/guideMarkdownOptions";

type GuideMarkdownProps = {
  source: string;
};

// 공용 `Markdown`(약관·공지)을 쓰지 않는 이유: 그쪽은 GFM 이라 `10~15턴` 같은 범위에 취소선이 그어지고,
// 원문 HTML 을 글자로 찍으며, 요소 매핑을 바꿀 수 없다. 약관·공지 렌더는 건드리지 않고 여기서 따로 그린다.
const COMPONENTS: Components = {
  p: GuideParagraph,
  h3: GuideSubheading,
  ul: GuideUl,
  ol: GuideOl,
  a: GuideLink,
  strong: GuideStrong,
  code: GuideInlineCode,
  blockquote: GuideBlockquote,
  hr: GuideHr,
};

/** 원고에서 예시 블록과 절 제목을 뺀 본문 조각. */
export function GuideMarkdown({ source }: GuideMarkdownProps) {
  return (
    <div className="flex min-w-0 flex-col gap-3 break-keep wrap-break-word text-sm leading-relaxed text-foreground">
      <Markdown {...GUIDE_MARKDOWN_OPTIONS} components={COMPONENTS}>
        {source}
      </Markdown>
    </div>
  );
}

function GuideParagraph({ className, node: _node, ...props }: ComponentProps<"p"> & ExtraProps) {
  return <p className={cn("m-0", className)} {...props} />;
}

/** 절(h2) 아래 한 단계. 18px 소제목 티어다. */
function GuideSubheading({ className, node: _node, ...props }: ComponentProps<"h3"> & ExtraProps) {
  return <h3 className={cn("mt-3 text-lg font-semibold tracking-tight text-foreground", className)} {...props} />;
}

function GuideUl({ className, node: _node, ...props }: ComponentProps<"ul"> & ExtraProps) {
  return (
    <ul className={cn("m-0 flex list-disc flex-col gap-1.5 pl-5 marker:text-muted-foreground", className)} {...props} />
  );
}

function GuideOl({ className, node: _node, ...props }: ComponentProps<"ol"> & ExtraProps) {
  return (
    <ol
      className={cn("m-0 flex list-decimal flex-col gap-1.5 pl-5 marker:text-muted-foreground", className)}
      {...props}
    />
  );
}

/** 문장 속 링크 — 저장소의 인라인 링크 관용구(`LegalConsentFields` 의 약관 링크)와 같다. 포커스는 밑줄로 준다. */
function GuideLink({ className, node: _node, ...props }: ComponentProps<"a"> & ExtraProps) {
  return (
    <a
      className={cn("font-medium text-primary underline-offset-4 hover:underline focus-visible:underline", className)}
      {...props}
    />
  );
}

function GuideStrong({ className, node: _node, ...props }: ComponentProps<"strong"> & ExtraProps) {
  return <strong className={cn("font-semibold", className)} {...props} />;
}

/**
 * 인라인 코드 — 원고가 `*지문*` 같은 입력 표기를 문장 속에서 보여 줄 때 쓴다. 채팅의 인라인 코드와 같은
 * 모양이다(고정폭 없이 반투명 전경색 면만 깐다). 코드 블록은 허용 요소가 아니라 여기로 오는 것은 인라인뿐이다.
 */
function GuideInlineCode({ className, node: _node, ...props }: ComponentProps<"code"> & ExtraProps) {
  return <code className={cn("rounded-sm bg-foreground/10 px-1 py-0.5", className)} {...props} />;
}

/** 덧붙이는 말(팁·주의). 본문과 같은 크기로 두고 흐린 글자와 무채 1px 선으로만 가른다. */
function GuideBlockquote({ className, node: _node, ...props }: ComponentProps<"blockquote"> & ExtraProps) {
  return (
    <blockquote
      className={cn("m-0 flex flex-col gap-2 border-l border-border pl-3 text-muted-foreground", className)}
      {...props}
    />
  );
}

function GuideHr({ className, node: _node, ...props }: ComponentProps<"hr"> & ExtraProps) {
  return <hr className={cn("m-0 h-px shrink-0 border-0 bg-border", className)} {...props} />;
}
