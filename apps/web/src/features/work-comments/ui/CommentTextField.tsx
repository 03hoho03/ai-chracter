import { useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useFormContext, useWatch } from "react-hook-form";

import { countCommentGraphemes, uniqueComments, useCommentCandidatesQuery, type CommentAuthor } from "@/entities/comment";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import { findCommentMentionToken } from "../model/mentionToken";
import { COMMENT_MAX_GRAPHEMES, COMMENT_MAX_MENTIONS, COMMENT_MENTION_LIMIT_MESSAGE, type CommentFormValues } from "../model/schema";

type CommentTextFieldProps = {
  contentId: string; viewerId: string; canMention: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>; autoFocus?: boolean; mentionsErrorId?: string;
};

export function CommentTextField({
  contentId, viewerId, canMention, inputRef, autoFocus = false, mentionsErrorId,
}: CommentTextFieldProps) {
  const form = useFormContext<CommentFormValues>();
  const body = useWatch({ control: form.control, name: "body" });
  const mentions = useWatch({ control: form.control, name: "mentions" });
  const id = useId();
  const listId = id + "-mentions";
  const [caret, setCaret] = useState(body.length);
  const [isComposing, setIsComposing] = useState(false);
  const [dismissed, setDismissed] = useState<string>();
  const [activeIndex, setActiveIndex] = useState(0);
  const [position, setPosition] = useState<{ host: HTMLElement; left: number; top: number; width: number; maxHeight: number; isAbove: boolean; isInModal: boolean }>();
  const popupRef = useRef<HTMLDivElement>(null);
  const token = findCommentMentionToken(body, caret);
  const signature = token ? String(token.start) + ":" + token.q : "";
  const isOpen = !!token && canMention && !isComposing && dismissed !== signature;
  const candidates = useCommentCandidatesQuery(contentId, viewerId, token?.q ?? "", isOpen);
  const items = uniqueComments(candidates.data?.pages.flatMap((page) => page.items) ?? [])
    .filter((author) => !mentions.some((selected) => selected.id === author.id));
  const active = Math.min(activeIndex, Math.max(0, items.length - 1));
  const field = form.register("body");
  const bodyError = form.formState.errors.body;
  const mentionsError = form.formState.errors.mentions;

  useEffect(() => {
    function handleKeepInputVisible() {
      requestAnimationFrame(() => {
        const input = inputRef.current;
        const visible = window.visualViewport;
        if (!input || document.activeElement !== input || !visible) return;
        const scroll = input.closest<HTMLElement>("[data-content-detail-scroll]");
        const area = scroll?.getBoundingClientRect();
        const playBar = input.closest("[data-content-detail]")?.querySelector("[data-content-play-bar]")?.getBoundingClientRect();
        const top = Math.max(visible.offsetTop + 16, (area?.top ?? visible.offsetTop) + 8);
        let bottom = Math.min(visible.offsetTop + visible.height - 16, (area?.bottom ?? Infinity) - 8);
        if (playBar && playBar.top > top && playBar.top < bottom) bottom = playBar.top - 12;
        const rect = input.getBoundingClientRect();
        let delta = 0;
        if (rect.bottom > bottom) delta = rect.bottom - bottom;
        else if (rect.top < top) delta = rect.top - top;
        if (delta) { if (scroll) scroll.scrollBy({ top: delta }); else window.scrollBy({ top: delta }); }
      });
    }
    window.visualViewport?.addEventListener("resize", handleKeepInputVisible);
    const input = inputRef.current;
    input?.addEventListener("focus", handleKeepInputVisible);
    return () => { window.visualViewport?.removeEventListener("resize", handleKeepInputVisible); input?.removeEventListener("focus", handleKeepInputVisible); };
  }, [inputRef]);

  useLayoutEffect(() => {
    if (!isOpen) return;
    function measure() {
      const input = inputRef.current;
      if (!input) return;
      const dialog = input.closest<HTMLElement>('[role="dialog"]');
      const host = dialog ?? document.body;
      const rect = input.getBoundingClientRect();
      const hostRect = dialog?.getBoundingClientRect();
      const visibleBottom = window.visualViewport
        ? window.visualViewport.offsetTop + window.visualViewport.height : window.innerHeight;
      const visibleTop = window.visualViewport?.offsetTop ?? 0;
      const aboveRoom = Math.max(0, rect.top - visibleTop - 16);
      const belowRoom = Math.max(0, visibleBottom - rect.bottom - 16);
      const isAbove = belowRoom < 180 && aboveRoom > belowRoom;
      const maxHeight = Math.max(40, Math.min(240, isAbove ? aboveRoom : belowRoom));
      const scale = dialog && hostRect ? hostRect.width / dialog.offsetWidth : 1;
      setPosition({
        host, isInModal: !!dialog, left: (rect.left - (hostRect?.left ?? 0)) / scale,
        top: ((isAbove ? rect.top - 4 : rect.bottom + 4) - (hostRect?.top ?? 0)) / scale,
        width: Math.min(rect.width, window.innerWidth - 32) / scale, maxHeight: maxHeight / scale, isAbove,
      });
    }
    measure();
    const settled = window.setTimeout(measure, 150);
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("resize", measure);
    return () => {
      window.clearTimeout(settled);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("resize", measure);
    };
  }, [isOpen, inputRef]);

  useEffect(() => {
    if (!isOpen) return;
    function handleOutsidePointer(event: PointerEvent) {
      if (event.target instanceof Node && !inputRef.current?.contains(event.target) && !popupRef.current?.contains(event.target)) setDismissed(signature);
    }
    document.addEventListener("pointerdown", handleOutsidePointer);
    return () => document.removeEventListener("pointerdown", handleOutsidePointer);
  }, [isOpen, inputRef, signature]);

  function handleChoose(author: CommentAuthor) {
    if (!token || mentions.length >= COMMENT_MAX_MENTIONS) return;
    form.setValue("mentions", [...mentions, author], { shouldDirty: true, shouldValidate: true });
    // The selected account lives in an ID-backed chip; the typed search fragment is removed.
    form.setValue("body", body.slice(0, token.start) + body.slice(token.end), { shouldDirty: true });
    setDismissed(signature);
    setCaret(token.start);
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(token.start, token.start);
    });
  }

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Label htmlFor={id}>댓글 내용</Label>
      <Textarea {...field} id={id} rows={3} autoFocus={autoFocus}
        ref={(element) => { field.ref(element); inputRef.current = element; }}
        role="combobox" aria-autocomplete="list" aria-expanded={isOpen} aria-controls={isOpen ? listId : undefined}
        aria-activedescendant={isOpen && items[active] ? listId + "-" + items[active]?.id : undefined}
        aria-invalid={!!bodyError || !!mentionsError} aria-describedby={[id + "-count", bodyError ? id + "-error" : undefined, mentionsError ? mentionsErrorId : undefined].filter(Boolean).join(" ")}
        placeholder="작품을 보고 느낀 이야기를 남겨보세요."
        className="min-h-24 scroll-mb-32 resize-y"
        onChange={(event) => { void field.onChange(event); setCaret(event.currentTarget.selectionStart); setActiveIndex(0); setDismissed(undefined); }}
        onClick={(event) => setCaret(event.currentTarget.selectionStart)}
        onKeyUp={(event) => setCaret(event.currentTarget.selectionStart)}
        onCompositionStart={() => setIsComposing(true)} onCompositionEnd={() => setIsComposing(false)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing || isComposing || event.keyCode === 229) return;
          if (event.key === "Tab") setDismissed(signature);
          if (!isOpen) return;
          if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setDismissed(signature); }
          else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((current) => Math.max(0, Math.min(items.length - 1, current + (event.key === "ArrowDown" ? 1 : -1))));
          } else if (event.key === "Enter" && items[active] && mentions.length < COMMENT_MAX_MENTIONS) {
            event.preventDefault();
            const author = items[active];
            if (author) handleChoose(author);
          }
        }} />
      <CharacterCount id={id + "-count"} count={countCommentGraphemes(body)} max={COMMENT_MAX_GRAPHEMES}
        help={canMention ? "Enter는 줄바꿈 · @로 작품 참여자 멘션" : "Enter는 줄바꿈 · 멘션 선택은 참여 가능한 로그인 상태에서 이용해요."} />
      {!!bodyError && <p id={id + "-error"} role="alert" className="text-xs text-destructive-text">{bodyError.message}</p>}
      {isOpen && !!position && createPortal(
        <div ref={popupRef} className="z-[60] overflow-y-auto rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10"
          style={{ position: position.isInModal ? "absolute" : "fixed", left: position.left, top: position.top, width: position.width,
            maxHeight: position.maxHeight, transform: position.isAbove ? "translateY(-100%)" : undefined }}
          onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setDismissed(signature); inputRef.current?.focus(); } }}>
          <div id={listId} role="listbox" aria-label="멘션할 사용자">
            <CommentMentionCandidates candidates={candidates} items={items} activeIndex={active} listId={listId}
              canSelect={mentions.length < COMMENT_MAX_MENTIONS} onSelect={handleChoose} />
          </div>
          {mentions.length >= COMMENT_MAX_MENTIONS && <p className="p-2 text-xs text-muted-foreground">{COMMENT_MENTION_LIMIT_MESSAGE}</p>}
          {candidates.hasNextPage && <Button type="button" size="sm" variant="ghost" className="w-full hover:bg-secondary"
            aria-disabled={candidates.isFetchingNextPage} onClick={() => { if (!candidates.isFetchingNextPage) void candidates.fetchNextPage(); }}>참여자 더 보기</Button>}
        </div>, position.host,
      )}
    </div>
  );
}


type CommentMentionCandidatesProps = {
  candidates: ReturnType<typeof useCommentCandidatesQuery>; items: CommentAuthor[]; activeIndex: number;
  listId: string; canSelect: boolean; onSelect: (author: CommentAuthor) => void;
};

function CommentMentionCandidates({ candidates, items, activeIndex, listId, canSelect, onSelect }: CommentMentionCandidatesProps) {
  function handleRetry() { if (candidates.isFetchNextPageError) void candidates.fetchNextPage(); else void candidates.refetch(); }
  const error = <div className="p-2 text-xs"><p>멘션 후보를 불러오지 못했어요.</p><Button type="button" size="sm" variant="outline" onClick={handleRetry}>다시 시도</Button></div>;
  if (candidates.isPending) return <p className="p-2 text-xs text-muted-foreground">참여자를 찾는 중…</p>;
  if (candidates.isError && !candidates.data) return error;
  if (!candidates.isError && items.length === 0) return <p className="p-2 text-xs text-muted-foreground">선택할 참여자가 없어요. 일반 텍스트는 계속 쓸 수 있어요.</p>;
  return <>
    {items.map((author, index) => <button key={author.id} id={listId + "-" + author.id} type="button" role="option" tabIndex={-1}
      aria-selected={index === activeIndex} aria-disabled={!canSelect}
      onPointerDown={(event) => event.preventDefault()} onClick={() => onSelect(author)}
      className={cn("group flex w-full min-w-0 flex-col rounded-md px-2 py-2 text-left text-xs hover:bg-secondary", index === activeIndex && "bg-secondary inset-ring-1 inset-ring-ring")}>
      <span className="break-all font-medium">{author.nickname}{author.isCreator && " · 작가"}</span>
      <span className={cn("break-all group-hover:text-foreground", index === activeIndex ? "text-foreground" : "text-muted-foreground")}>계정 {author.id.slice(0, 8)}</span>
    </button>)}
    {candidates.isError && error}
  </>;
}
