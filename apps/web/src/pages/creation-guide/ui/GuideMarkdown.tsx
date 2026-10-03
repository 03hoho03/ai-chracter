import type { ComponentProps } from "react";
import type { Components, ExtraProps } from "react-markdown";
import Markdown from "react-markdown";

import { cn } from "@ai-character-chat/ui/lib/utils";

import { GUIDE_MARKDOWN_OPTIONS } from "../config/guideMarkdownOptions";
import { GUIDE_QUIET_LINK_CLASS } from "../config/guideStyles";

export type GuideMarkdownProps = {
  source: string;
  /**
   * 원고의 `###` 소제목을 몇 수준 제목으로 그릴지. 절 제목(h2) 아래에 있으면 3, 단계 페이지처럼 페이지 제목(h1) 바로
   * 아래에 놓이면 2 — 제목 수준을 건너뛰면 제목으로 훑는 낭독기 사용자가 빠진 단계를 찾게 된다.
   */
  headingLevel?: 2 | 3;
  /**
   * 링크 모양. 기본은 문장 속 강조 링크이고, `quiet` 은 칸 링크가 여럿 몰리는 목록(자주 하는 실수)용 흐린 밑줄 링크다 —
   * 강조색 링크가 열 개 넘게 모이면 유채색이 한 덩어리가 된다.
   */
  linkTone?: "accent" | "quiet";
  className?: string;
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
export function GuideMarkdown({ source, headingLevel = 3, linkTone = "accent", className }: GuideMarkdownProps) {
  const components: Components = {
    ...COMPONENTS,
    ...(headingLevel === 2 && { h3: GuidePageSubheading }),
    ...(linkTone === "quiet" && { a: GuideQuietLink }),
  };
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-3 break-keep wrap-break-word text-sm leading-relaxed text-foreground",
        className,
      )}
    >
      <Markdown {...GUIDE_MARKDOWN_OPTIONS} components={components}>
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

/** 페이지 제목 바로 아래에 놓인 소제목 — 원고의 `###` 를 h2 로 그린다(모양은 같다). */
function GuidePageSubheading({ className, node: _node, ...props }: ComponentProps<"h3"> & ExtraProps) {
  return <h2 className={cn("mt-3 text-lg font-semibold tracking-tight text-foreground", className)} {...props} />;
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

function GuideQuietLink({ className, node: _node, ...props }: ComponentProps<"a"> & ExtraProps) {
  return <a className={cn(GUIDE_QUIET_LINK_CLASS, className)} {...props} />;
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
