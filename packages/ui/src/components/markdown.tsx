import type { ComponentProps } from "react"
import type { Components, ExtraProps } from "react-markdown"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@ai-character-chat/ui/lib/utils"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./table"

type MarkdownProps = {
  content: string
  className?: string
}

function Markdown({ content, className }: MarkdownProps) {
  return (
    <div
      data-slot="markdown"
      className={cn(
        "flex flex-col gap-3 break-keep text-sm text-foreground",
        className
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

const markdownComponents: Components = {
  h1: MarkdownH1,
  h2: MarkdownH2,
  h3: MarkdownH3,
  h4: MarkdownH4,
  p: MarkdownParagraph,
  ul: MarkdownUl,
  ol: MarkdownOl,
  a: MarkdownLink,
  strong: MarkdownStrong,
  blockquote: MarkdownBlockquote,
  hr: MarkdownHr,
  code: MarkdownCode,
  table: Table,
  thead: TableHeader,
  tbody: TableBody,
  tr: TableRow,
  th: TableHead,
  td: TableCell,
}

function MarkdownH1({
  className,
  node: _node,
  ...props
}: ComponentProps<"h1"> & ExtraProps) {
  return (
    <h1
      className={cn("m-0 text-xl font-semibold tracking-tight", className)}
      {...props}
    />
  )
}

function MarkdownH2({
  className,
  node: _node,
  ...props
}: ComponentProps<"h2"> & ExtraProps) {
  return (
    <h2 className={cn("m-0 text-base font-semibold", className)} {...props} />
  )
}

function MarkdownH3({
  className,
  node: _node,
  ...props
}: ComponentProps<"h3"> & ExtraProps) {
  return (
    <h3 className={cn("m-0 text-sm font-semibold", className)} {...props} />
  )
}

function MarkdownH4({
  className,
  node: _node,
  ...props
}: ComponentProps<"h4"> & ExtraProps) {
  return (
    <h4 className={cn("m-0 text-sm font-medium", className)} {...props} />
  )
}

function MarkdownParagraph({
  className,
  node: _node,
  ...props
}: ComponentProps<"p"> & ExtraProps) {
  return <p className={cn("m-0 leading-relaxed", className)} {...props} />
}

function MarkdownUl({
  className,
  node: _node,
  ...props
}: ComponentProps<"ul"> & ExtraProps) {
  return (
    <ul
      className={cn(
        "m-0 list-disc pl-6 marker:text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function MarkdownOl({
  className,
  node: _node,
  ...props
}: ComponentProps<"ol"> & ExtraProps) {
  return (
    <ol
      className={cn(
        "m-0 list-decimal pl-6 marker:text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function MarkdownLink({
  className,
  node: _node,
  ...props
}: ComponentProps<"a"> & ExtraProps) {
  return (
    <a
      className={cn(
        "font-medium text-primary underline underline-offset-4",
        className
      )}
      {...props}
    />
  )
}

function MarkdownStrong({
  className,
  node: _node,
  ...props
}: ComponentProps<"strong"> & ExtraProps) {
  return <strong className={cn("font-semibold", className)} {...props} />
}

function MarkdownBlockquote({
  className,
  node: _node,
  ...props
}: ComponentProps<"blockquote"> & ExtraProps) {
  return (
    <blockquote
      className={cn(
        "m-0 border-l-2 border-border pl-4 text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function MarkdownHr({
  className,
  node: _node,
  ...props
}: ComponentProps<"hr"> & ExtraProps) {
  return (
    <hr className={cn("m-0 border-0 border-t border-border", className)} {...props} />
  )
}

function MarkdownCode({
  className,
  node: _node,
  ...props
}: ComponentProps<"code"> & ExtraProps) {
  // 코드 전용 서체를 쓰지 않는다 — Single Family Rule(Pretendard 하나)을 지키고
  // 배경 틴트만으로 코드 구간을 구분한다.
  return (
    <code
      className={cn("rounded-sm bg-muted px-1 py-0.5 text-sm", className)}
      {...props}
    />
  )
}

export { Markdown }
