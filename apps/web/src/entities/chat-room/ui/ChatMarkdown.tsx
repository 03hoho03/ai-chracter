import { memo, type ComponentProps } from "react";
import type { Components, ExtraProps } from "react-markdown";
import Markdown from "react-markdown";
import { Copy } from "lucide-react";

import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";

import { dropUnresolvedMediaTags } from "@/entities/media-book/@x/chat-room";
import { expandAuthorMacros } from "@/shared/lib/text/authorMacros";
import { MediaImageFrame, type MediaImageSurface } from "@/shared/ui/media-image-frame/MediaImageFrame";

import { CHAT_MARKDOWN_MEDIA_OPTIONS, CHAT_MARKDOWN_OPTIONS, prepareChatMarkdownSource } from "../lib/chatMarkdown";
import { copyCodeToClipboard } from "../lib/copyCodeToClipboard";
import { useAuthorMacroNames } from "../model/useAuthorMacroNames";
import { useMediaTagImages } from "../model/useMediaTagImages";

// 코드 블록과 글 속 그림 자리가 같은 면 값을 받으므로 그림 틀의 면 종류를 그대로 쓴다.
type CodeBlockSurface = MediaImageSurface;

type ChatMarkdownProps = {
  content: string;
  /**
   * 코드 블록과 글 속 그림 자리의 면. `bg-muted` 는 card·popover 면과 값이 같아 그 위에서 사라지므로, 다이얼로그
   * 안에서는 `secondary` 를 준다.
   */
  codeBlockSurface?: CodeBlockSurface;
  className?: string;
};

type HastNode = ExtraProps["node"];
type ChatCodeBlockProps = ComponentProps<"pre"> & ExtraProps & { surface: CodeBlockSurface };
type ChatMediaTagImageProps = ComponentProps<"img"> & ExtraProps & { surface: CodeBlockSurface };

const CODE_BLOCK_SURFACE_CLASS: Record<CodeBlockSurface, string> = {
  muted: "bg-muted",
  secondary: "bg-secondary",
};

const BASE_COMPONENTS: Components = {
  p: ChatParagraph,
  em: ChatNarration,
  strong: ChatStrong,
  blockquote: ChatBlockquote,
  hr: ChatHr,
  ul: ChatUl,
  ol: ChatOl,
  code: ChatInlineCode,
};

// 컴포넌트 참조가 렌더마다 바뀌면 React 가 코드 블록을 매번 다시 마운트한다(스트리밍 중에는 토큰마다).
// 면마다 한 번만 만들어 둔다.
const COMPONENTS_BY_SURFACE: Record<CodeBlockSurface, Components> = {
  muted: {
    ...BASE_COMPONENTS,
    pre: (props) => <ChatCodeBlock {...props} surface="muted" />,
    img: (props) => <ChatMediaTagImage {...props} surface="muted" />,
  },
  secondary: {
    ...BASE_COMPONENTS,
    pre: (props) => <ChatCodeBlock {...props} surface="secondary" />,
    img: (props) => <ChatMediaTagImage {...props} surface="secondary" />,
  },
};

// 메시지 목록 화면은 입력창 글자·스트리밍 청크마다 다시 렌더되는데, 본문이 그대로인 메시지까지 매번
// 마크다운을 다시 파싱하면 긴 대화에서 입력이 끊긴다. props 가 전부 원시값이라 기본 얕은 비교로 건너뛴다.
export const ChatMarkdown = memo(function ChatMarkdown({
  content,
  codeBlockSurface = "muted",
  className,
}: ChatMarkdownProps) {
  // 그림 맵은 `MediaTagImagesProvider` 로 감싼 메시지(작성자 글)에만 있다. 없으면 태그는 글자 그대로다.
  const mediaTagImages = useMediaTagImages();
  // 이름은 `AuthorMacroNamesProvider` 로 감싼 작성자 글에만 있다. 그림 태그를 먼저 처리하고 이름을 나중에 넣는다 —
  // 넣은 이름이 태그로 읽히지 않게. 마크다운 파싱 전이라 이름 속 표기 문자는 이름 규칙이 막는다(`userNameError`).
  const authorMacroNames = useAuthorMacroNames();
  const withoutUnresolvedTags =
    mediaTagImages === undefined ? content : dropUnresolvedMediaTags(content, mediaTagImages);
  const source =
    authorMacroNames === undefined ? withoutUnresolvedTags : expandAuthorMacros(withoutUnresolvedTags, authorMacroNames);
  // `break-words` 가 아니라 `wrap-break-word` 인 이유: tailwind-merge 가 `break-words` 와 `break-keep` 을
  // 같은 무리로 보고 앞의 것을 지운다. 둘 다 살아 있어야 어절은 지키고 긴 URL 같은 한 덩어리는 접힌다.
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-3 break-keep wrap-break-word text-sm leading-relaxed text-foreground",
        className,
      )}
    >
      <Markdown
        {...(mediaTagImages === undefined ? CHAT_MARKDOWN_OPTIONS : CHAT_MARKDOWN_MEDIA_OPTIONS)}
        components={COMPONENTS_BY_SURFACE[codeBlockSurface]}
      >
        {prepareChatMarkdownSource(source)}
      </Markdown>
    </div>
  );
});

function ChatParagraph({ className, node: _node, ...props }: ComponentProps<"p"> & ExtraProps) {
  return <p className={cn("m-0", className)} {...props} />;
}

/** 지문. 별표는 이미 빠졌고, 이탤릭은 한글 글리프를 기울여 깨뜨리므로 색으로만 대사와 가른다. */
function ChatNarration({ className, node: _node, ...props }: ComponentProps<"em"> & ExtraProps) {
  return <em className={cn("not-italic text-muted-foreground", className)} {...props} />;
}

function ChatStrong({ className, node: _node, ...props }: ComponentProps<"strong"> & ExtraProps) {
  return <strong className={cn("font-semibold", className)} {...props} />;
}

/** 장면 헤더(`> D+0 | 13:00 | 장소`) 용도라 본문보다 한 단계 작고 흐리다. 좌측 선은 장식이라 무채색 1px. */
function ChatBlockquote({ className, node: _node, ...props }: ComponentProps<"blockquote"> & ExtraProps) {
  return (
    <blockquote
      className={cn("m-0 flex flex-col gap-1 border-l border-border pl-3 text-xs text-muted-foreground", className)}
      {...props}
    />
  );
}

function ChatHr({ className, node: _node, ...props }: ComponentProps<"hr"> & ExtraProps) {
  return <hr className={cn("m-0 h-px shrink-0 border-0 bg-border", className)} {...props} />;
}

// 목록은 본문 컬럼 안의 짧은 나열이라 들여쓰기는 두 자리 번호가 들어갈 만큼만 준다.
function ChatUl({ className, node: _node, ...props }: ComponentProps<"ul"> & ExtraProps) {
  return <ul className={cn("m-0 list-disc pl-5 marker:text-muted-foreground", className)} {...props} />;
}

function ChatOl({ className, node: _node, ...props }: ComponentProps<"ol"> & ExtraProps) {
  return <ol className={cn("m-0 list-decimal pl-5 marker:text-muted-foreground", className)} {...props} />;
}

/**
 * 인라인 코드. 코드 블록은 `pre` 가 통째로 그리므로 여기로 오는 것은 문장 속 코드뿐이다.
 * 고정폭을 쓰지 않고 옅은 면으로만 구간을 표시한다 — 반투명 전경색이라 어느 면 위에서도 사라지지 않는다.
 */
function ChatInlineCode({ className, node: _node, ...props }: ComponentProps<"code"> & ExtraProps) {
  return <code className={cn("rounded-sm bg-foreground/10 px-1 py-0.5", className)} {...props} />;
}

/**
 * 코드 블록. 언어 태그는 쓰지 않으므로 react-markdown 이 만든 `<code class="language-…">` 를 버리고
 * 원문 글자만 다시 그린다.
 * 줄은 가로 스크롤 대신 접는다(`whitespace-pre-wrap`) — 채팅 코드 블록은 대개 상태창 같은 글이라 좁은
 * 화면에서 가로로 밀어 읽게 할 이유가 없고, `overflow-x-auto` 는 복사 버튼의 포커스 링까지 잘라 낸다.
 */
function ChatCodeBlock({ node, surface }: ChatCodeBlockProps) {
  const code = collectText(node).replace(/\n$/, "");
  const handleCopy = () => {
    void copyCodeToClipboard(code);
  };

  return (
    <div className="relative">
      <pre
        className={cn(
          "m-0 whitespace-pre-wrap rounded-lg py-3 pr-11 pl-3 font-mono text-xs leading-relaxed",
          CODE_BLOCK_SURFACE_CLASS[surface],
        )}
      >
        <code>{code}</code>
      </pre>
      {/* ghost 의 hover 면(bg-muted)은 muted 코드 면과 같은 값이라 사라진다 — 반투명 전경색으로 덮어 어느 면에서도 보이게 한다. */}
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="코드 복사"
        className="absolute top-1.5 right-1.5 text-muted-foreground hover:bg-foreground/10"
        onClick={handleCopy}
      >
        <Copy aria-hidden />
      </Button>
    </div>
  );
}

/**
 * 글 속 미디어 북 그림. `img` 요소는 그림 맵이 있는 자리의 플러그인만 만든다(마크다운 이미지 문법은 파서에서 꺼져
 * 있다) — 요소가 가리키는 칸을 맵에서 찾아 그 주소와 크기로 그린다.
 */
function ChatMediaTagImage({ node, surface }: ChatMediaTagImageProps) {
  const images = useMediaTagImages();
  const cellId = node?.properties.dataCellId;
  const image = typeof cellId === "string" ? images?.[cellId] : undefined;
  if (image === undefined) return null;
  return <MediaImageFrame url={image.url} width={image.width} height={image.height} alt="작품 속 이미지" surface={surface} />;
}

function collectText(node: HastNode): string {
  if (!node) return "";
  return node.children
    .map((child) => {
      if (child.type === "text") return child.value;
      if (child.type === "element") return collectText(child);
      return "";
    })
    .join("");
}
