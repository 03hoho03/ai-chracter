import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Sparkles, X } from "lucide-react";
import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import {
  novelKeys,
  toNovelActionError,
  type NovelChapterResponse,
  type NovelDetailResponse,
  type NovelPendingAiEdit,
} from "@/entities/novel";

import { useSaveChapterRevisionMutation } from "../api/useSaveChapterRevisionMutation";
import { countChapterChars, joinParagraphRange, toManualEditSave, type ManualEditBase } from "../model/chapterBody";
import {
  clampParagraphRange,
  formatParagraphRange,
  isParagraphInRange,
  nextParagraphRange,
  toParagraphSelectionAnnouncement,
  type ParagraphRange,
} from "../model/paragraphRange";
import type { NovelAiEditFlow } from "../model/useNovelAiEdit";

import { AiEditPreview } from "./AiEditPreview";

type NovelChapterTextProps = {
  novel: NovelDetailResponse;
  chapter: NovelChapterResponse;
  /** "고치기" 모드인가. 켜져 있을 때만 문단이 고를 수 있는 버튼이 된다. */
  isFixMode: boolean;
  aiEdit: NovelAiEditFlow;
  /** 누른 버튼이 사라지는 일(수정안 적용·버리기)이 끝난 뒤 포커스를 둘 곳 — 장 제목. */
  onFocusFallback: () => void;
  /** 직접 고치는 글이 시작할 때와 달라졌는가가 바뀔 때마다 알린다(사라질 때는 `false`). 화면이 장을 옮기기 전에
   * 이 값으로 확인을 받는다 — 장을 옮기면 이 컴포넌트가 새로 마운트돼 쓰던 글이 없어진다. */
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/** 직접 고치기 하나. `base` 는 시작한 순간의 판·문단·범위라 그사이 본문이 바뀌어도 그대로다. */
type ManualEdit = { base: ManualEditBase; draft: string };

/** 장 본문과 그 위의 고치기 전부: 문단 고르기, 직접 고치기, AI 수정안 미리보기.
 *
 * - **읽기**: `<article>` 안 평범한 `<p>` 나열이다. 서버가 나눈 문단을 그대로 쓰고(화면이 다시 나누면 AI 수정의
 *   문단 범위가 어긋난다), 마크다운·지문 표기 해석은 하지 않는다. 이탤릭 없음, 읽기 폭은 `max-w-prose`.
 * - **고르기**: 고치기 모드에서만 문단이 `aria-pressed` 버튼이 되고, 묶음은 `role="group"` 이다. 읽다가 잘못
 *   눌러 골라지는 일이 없고, 브라우저 글자 선택을 쓰지 않아 길게 누르기·키보드 문제가 없다. 범위 규칙은
 *   `nextParagraphRange` 하나다. 고른 문단은 회색 면 + 무채색 윤곽으로 보이고(유채색 채움 없음), 키보드 포커스는
 *   그보다 두꺼운 강조색 링이라 둘이 모양으로 갈린다. 무엇을 골랐는지는 항상 마운트된 한 줄이 알린다.
 * - **동작 줄**: 고른 범위의 마지막 문단 바로 아래, 문서 흐름 안에 둔다. 화면 아래에 붙는 고정 막대는 이 앱의
 *   크롬 규칙(상시 크롬은 위쪽 머리 하나)에 어긋난다.
 * - **직접 고치기**: 고른 문단 자리에 입력칸이 들어선다(내용만큼 자란다). 시작한 순간의 판·문단을 잡아 두고 저장은
 *   그 문단으로 장 전체 본문을 조립해 그 판을 기준으로 보낸다 — 그사이 판이 바뀌었으면 서버가 409 로 막고, 입력한
 *   글은 그대로 둔다. */
export function NovelChapterText({
  novel,
  chapter,
  isFixMode,
  aiEdit,
  onFocusFallback,
  onDraftDirtyChange,
}: NovelChapterTextProps) {
  const queryClient = useQueryClient();
  const groupLabelId = useId();
  const editorId = useId();
  const aiBlockedReasonId = useId();
  const paragraphs = chapter.revision.paragraphs;
  const [range, setRange] = useState<ParagraphRange | null>(null);
  const [manualEdit, setManualEdit] = useState<ManualEdit | null>(null);
  // 저장 실패 문장. 저장을 누른 순간에 기록하고 다음 저장·취소에서만 지운다 — 409 뒤 상세를 다시 받아도 남는다.
  const [editError, setEditError] = useState<string | undefined>(undefined);
  // 고르기·저장의 결과를 알리는 한 줄. 일이 일어난 순간에 기록한다.
  const [liveMessage, setLiveMessage] = useState("");
  const saveMutation = useSaveChapterRevisionMutation();
  const paragraphButtonsRef = useRef(new Map<number, HTMLButtonElement>());
  const pendingFocusIndexRef = useRef<number | undefined>(undefined);

  // 다른 곳의 수정을 다시 받아 문단 수가 줄었으면 범위를 남은 문단 안으로 접는다.
  const activeRange = isFixMode ? clampParagraphRange(range, paragraphs.length) : null;
  // 입력칸을 놓을 자리. 범위는 시작한 판의 것이라, 다른 곳의 수정으로 문단 수가 줄었으면 남은 문단 안으로 접는다.
  const editRange = manualEdit ? clampParagraphRange(manualEdit.base.range, paragraphs.length) : null;
  // 시작한 뒤 판이 바뀌었는가. 그러면 저장은 서버가 충돌로 막고, 입력칸 자리의 새 글은 입력칸에 가려 보이지 않는다.
  const isEditStale = manualEdit !== null && manualEdit.base.revisionId !== chapter.revision.id;
  const isDraftDirty =
    manualEdit !== null && manualEdit.draft !== joinParagraphRange(manualEdit.base.paragraphs, manualEdit.base.range);
  const pendingEdits = novel.pendingAiEdits.filter((edit) => edit.chapterId === chapter.id);
  const isSaving = saveMutation.isPending;

  useEffect(() => {
    onDraftDirtyChange(isDraftDirty);
    // 알릴 시점은 값이 바뀐 순간이다. 콜백은 호출부의 ref 쓰기라 렌더마다 같은 일을 한다.
  }, [isDraftDirty]);
  useEffect(() => () => onDraftDirtyChange(false), []);

  // 모드를 끄면 고른 것도 푼다(입력 중인 직접 고치기는 그대로 둔다 — 쓰던 글을 지우지 않는다).
  useEffect(() => {
    if (isFixMode) return;
    setRange(null);
    setLiveMessage("");
  }, [isFixMode]);

  // 입력칸이 닫힌 뒤(저장·취소) 그 자리의 첫 문단 버튼으로 포커스를 돌린다. 버튼은 입력칸이 사라진 다음 렌더에
  // 생기므로 렌더 뒤에 옮긴다. 고치기 모드가 꺼져 있으면 문단이 버튼이 아니라 장 제목으로 간다.
  useEffect(() => {
    const index = pendingFocusIndexRef.current;
    if (index === undefined || manualEdit !== null) return;
    pendingFocusIndexRef.current = undefined;
    const button = paragraphButtonsRef.current.get(Math.min(index, paragraphs.length - 1));
    if (button) {
      button.focus();
      return;
    }
    onFocusFallback();
    // 옮길 시점은 입력칸이 닫힌 렌더 하나다.
  }, [manualEdit]);

  function select(index: number, extend: boolean) {
    const next = nextParagraphRange(activeRange, index, { extend });
    setRange(next);
    setLiveMessage(toParagraphSelectionAnnouncement(next));
  }

  function clearSelection(focusIndex: number) {
    setRange(null);
    setLiveMessage("고른 문단을 풀었어요.");
    // 동작 줄이 사라지며 누른 버튼도 사라진다 — 마지막으로 고른 문단으로 포커스를 옮겨 둔다.
    paragraphButtonsRef.current.get(focusIndex)?.focus();
  }

  function startManualEdit(target: ParagraphRange) {
    setEditError(undefined);
    setManualEdit({
      base: { revisionId: chapter.revision.id, paragraphs, range: target },
      draft: joinParagraphRange(paragraphs, target),
    });
    setRange(null);
    setLiveMessage("");
  }

  function closeManualEdit(message: string) {
    if (editRange) pendingFocusIndexRef.current = editRange.start;
    setManualEdit(null);
    setEditError(undefined);
    setLiveMessage(message);
  }

  async function saveManualEdit() {
    if (isSaving || manualEdit === null || editRange === null) return;
    setEditError(undefined);
    const { baseRevisionId, body, isUnchanged } = toManualEditSave(manualEdit.base, manualEdit.draft);
    const length = countChapterChars(body);
    if (length === 0) {
      setEditError("장 본문을 모두 비울 수는 없어요.");
      return;
    }
    if (length > novel.limits.chapterBodyMaxLength) {
      setEditError(`장 본문은 ${novel.limits.chapterBodyMaxLength.toLocaleString()}자까지 쓸 수 있어요.`);
      return;
    }
    if (isUnchanged) {
      closeManualEdit("바뀐 내용이 없어 그대로 두었어요.");
      return;
    }
    try {
      await saveMutation.mutateAsync({
        novelId: novel.id,
        chapterId: chapter.id,
        baseRevisionId,
        body,
      });
      closeManualEdit("고친 내용을 저장했어요. 이전 글은 판 이력에 남아요.");
    } catch (error) {
      const result = toNovelActionError(error, "edit");
      // 재동의가 필요하면 전역 재동의 모달이 맡는다 — 입력칸은 그대로 두어 동의 뒤 다시 저장할 수 있다.
      if (result === null) return;
      setEditError(result.message);
      if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }

  async function startAiEdit(target: ParagraphRange) {
    const isStarted = await aiEdit.start({
      chapterId: chapter.id,
      chapterOrdinal: chapter.ordinal,
      revisionId: chapter.revision.id,
      paragraphs,
      range: target,
    });
    if (!isStarted) return;
    // 작업을 맡겼으면 고른 것을 푼다 — 수정안은 끝나면 그 문단 아래에 온다. 사라지는 동작 줄 대신 고른 범위의 첫
    // 문단으로 포커스를 둔다.
    setRange(null);
    setLiveMessage("");
    paragraphButtonsRef.current.get(target.start)?.focus();
  }

  async function handlePreviewAction(action: () => Promise<void>) {
    await action();
    // 적용하든 버리든 그 수정안 상자가 사라지며 누른 버튼도 사라진다 — 결과 안내가 있는 장 머리로 옮긴다.
    onFocusFallback();
  }

  function previewsEndingAt(index: number): NovelPendingAiEdit[] {
    const lastIndex = paragraphs.length - 1;
    return pendingEdits.filter((edit) => Math.min(edit.paragraphEnd, lastIndex) === index);
  }

  /** 문단 하나의 자리: 직접 고치는 범위면 그 첫 자리에 입력칸(나머지 자리는 비움), 고치기 모드면 고를 수 있는 버튼,
   * 아니면 평범한 문단. */
  function renderParagraph(paragraph: string, index: number) {
    if (editRange !== null && manualEdit !== null && isParagraphInRange(editRange, index)) {
      if (index !== editRange.start) return null;
      return (
        <ManualEditor
          id={editorId}
          rangeLabel={formatParagraphRange(editRange)}
          draft={manualEdit.draft}
          error={editError}
          isStale={isEditStale}
          hasPendingAiEdits={pendingEdits.length > 0}
          isSaving={isSaving}
          onDraftChange={(draft) => setManualEdit((current) => (current ? { ...current, draft } : current))}
          onCancel={() => closeManualEdit("직접 고치기를 그만뒀어요.")}
          onSave={() => void saveManualEdit()}
        />
      );
    }
    if (isFixMode) {
      return (
        <ParagraphButton
          ref={(element) => {
            if (element) paragraphButtonsRef.current.set(index, element);
            else paragraphButtonsRef.current.delete(index);
          }}
          text={paragraph}
          isSelected={isParagraphInRange(activeRange, index)}
          onSelect={(extend) => select(index, extend)}
        />
      );
    }
    return <p className="-mx-2 px-2 py-1 whitespace-pre-line">{paragraph}</p>;
  }

  const isAiBlocked = aiEdit.isBlocked;
  const aiBlockedReason = toAiBlockedReason(aiEdit);

  return (
    <div className="flex flex-col gap-3">
      {isFixMode && (
        <div className="flex flex-col gap-1">
          <p id={groupLabelId} className="text-sm break-keep text-muted-foreground">
            고칠 문단을 눌러 고르세요. 이어진 문단을 함께 고를 수 있어요.
          </p>
        </div>
      )}
      {/* 항상 마운트된 알림 줄 — 조건부로 붙이면 붙는 순간의 문장을 화면 낭독기가 놓친다. */}
      <p aria-live="polite" aria-atomic className="text-sm break-keep text-muted-foreground empty:sr-only">
        {liveMessage || null}
      </p>

      <article className="flex max-w-prose flex-col text-sm leading-relaxed break-keep text-foreground">
        <div
          role={isFixMode ? "group" : undefined}
          aria-label={isFixMode ? "고칠 문단 고르기" : undefined}
          aria-describedby={isFixMode ? groupLabelId : undefined}
          className="flex flex-col gap-3"
        >
          {paragraphs.map((paragraph, index) => {
            const isActionRowHere = activeRange !== null && activeRange.end === index && manualEdit === null;
            return (
              // 서버가 준 문단 순서가 곧 정체성이다(문단에 안정 id 가 없다 — 고르기 범위도 같은 인덱스를 쓴다).
              <Fragment key={index}>
                {renderParagraph(paragraph, index)}

                {isActionRowHere && (
                  <div className="flex flex-col gap-1.5 py-1">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        aria-disabled={isAiBlocked}
                        aria-describedby={aiBlockedReason !== undefined ? aiBlockedReasonId : undefined}
                        className="aria-disabled:opacity-65"
                        onClick={() => {
                          if (isAiBlocked) return;
                          void startAiEdit(activeRange);
                        }}
                      >
                        <Sparkles aria-hidden />
                        AI로 고치기
                      </Button>
                      <Button type="button" variant="outline" size="sm" onClick={() => startManualEdit(activeRange)}>
                        <Pencil aria-hidden />
                        직접 고치기
                      </Button>
                      <Button type="button" variant="ghost" size="sm" onClick={() => clearSelection(activeRange.end)}>
                        <X aria-hidden />
                        선택 해제
                      </Button>
                    </div>
                    {aiBlockedReason !== undefined && (
                      <p id={aiBlockedReasonId} className="text-sm break-keep text-muted-foreground">
                        {aiBlockedReason}
                      </p>
                    )}
                  </div>
                )}

                {previewsEndingAt(index).map((edit) => (
                  <AiEditPreview
                    key={edit.id}
                    edit={edit}
                    paragraphs={paragraphs}
                    isActing={aiEdit.actingEditId !== undefined}
                    onApply={() => void handlePreviewAction(() => aiEdit.apply(edit, chapter.ordinal))}
                    onDismiss={() => void handlePreviewAction(() => aiEdit.dismiss(edit))}
                  />
                ))}
              </Fragment>
            );
          })}
        </div>
      </article>
    </div>
  );
}

function toAiBlockedReason(aiEdit: NovelAiEditFlow): string | undefined {
  if (aiEdit.isRunning) return "AI로 고치는 중이에요. 끝나면 다시 고칠 수 있어요.";
  if (aiEdit.isOtherJobRunning) return "장을 쓰는 중이에요. 끝나면 AI로 고칠 수 있어요.";
  return undefined;
}

type ParagraphButtonProps = {
  ref: (element: HTMLButtonElement | null) => void;
  text: string;
  isSelected: boolean;
  /** `extend` 는 Shift 를 누른 채 눌렀는가. */
  onSelect: (extend: boolean) => void;
};

/** 고치기 모드의 문단 하나. 읽기 모드의 `<p>` 와 같은 상자(안쪽 여백·음수 바깥 여백)라 모드를 바꿔도 글자가
 * 움직이지 않는다. Shift+Enter 는 브라우저가 클릭으로 바꿔 주지 않아 키 입력에서 직접 받는다.
 *
 * 고른 윤곽(`aria-pressed:ring-*`)과 포커스 링(`focus-visible:ring-*`)은 같은 속성을 쓰고 선택자 특이도도 같아
 * 컴파일된 순서가 이기는데, Tailwind 4 는 `aria-pressed:` 규칙을 뒤에 낸다 — 그대로 두면 고른 문단에 포커스가
 * 있을 때(Enter 로 고른 직후가 그 상태다) 포커스 링이 1px 무채색 윤곽에 진다. 그래서 두 상태가 겹칠 때의 링을
 * `aria-pressed:focus-visible:` 로 다시 건다 — 이 규칙은 특이도가 하나 더 높아 순서와 상관없이 이긴다. */
function ParagraphButton({ ref, text, isSelected, onSelect }: ParagraphButtonProps) {
  return (
    <button
      ref={ref}
      type="button"
      aria-pressed={isSelected}
      className="-mx-2 cursor-pointer rounded-md px-2 py-1 text-left whitespace-pre-line outline-none motion-safe:transition-colors hover:bg-muted aria-pressed:bg-secondary aria-pressed:ring-1 aria-pressed:ring-foreground/20 aria-pressed:hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:focus-visible:ring-3 aria-pressed:focus-visible:ring-ring/50"
      onClick={(event: MouseEvent<HTMLButtonElement>) => onSelect(event.shiftKey)}
      onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => {
        if (event.key !== "Enter" || !event.shiftKey) return;
        event.preventDefault();
        onSelect(true);
      }}
    >
      {text}
    </button>
  );
}

type ManualEditorProps = {
  id: string;
  rangeLabel: string;
  draft: string;
  error: string | undefined;
  /** 시작한 뒤 이 장의 판이 바뀌었는가. */
  isStale: boolean;
  /** 이 장에 적용하지 않은 AI 수정안이 있는가. 저장하면 서버가 그 수정안을 버린다. */
  hasPendingAiEdits: boolean;
  isSaving: boolean;
  onDraftChange: (draft: string) => void;
  onCancel: () => void;
  onSave: () => void;
};

/** 고른 문단 자리에 들어서는 입력칸. 문단 사이는 빈 줄 하나로 띄운다(저장할 때 빈 줄로 다시 나뉜다). 버튼은
 * `취소` 먼저이고, 저장 중에는 `aria-disabled` 로 막아 누른 버튼의 포커스를 지킨다.
 *
 * 판이 바뀐 뒤에는 저장해도 충돌로 막힌다 — 쓴 글은 지우지 않고, 복사해 두고 최신 글에서 다시 고르라고 말한다.
 * 저장이 돈 낸 수정안을 버리게 되는 경우에는 저장 버튼 바로 위에서 미리 말한다. */
function ManualEditor({
  id,
  rangeLabel,
  draft,
  error,
  isStale,
  hasPendingAiEdits,
  isSaving,
  onDraftChange,
  onCancel,
  onSave,
}: ManualEditorProps) {
  return (
    <div className="flex flex-col gap-2 py-1">
      <Label htmlFor={id}>{rangeLabel} 직접 고치기</Label>
      <Textarea
        id={id}
        autoFocus
        value={draft}
        aria-invalid={error !== undefined}
        aria-describedby={`${id}-hint${error !== undefined ? ` ${id}-error` : ""}`}
        className="leading-relaxed break-keep"
        onChange={(event) => onDraftChange(event.target.value)}
      />
      <p id={`${id}-hint`} className="text-xs break-keep text-muted-foreground">
        문단 사이는 빈 줄 하나로 띄워 주세요. 모두 지우면 고른 문단이 빠져요.
      </p>
      {error !== undefined && (
        <p id={`${id}-error`} role="alert" className="text-sm break-keep text-destructive-text">
          {error}
        </p>
      )}
      {isStale && (
        <p className="text-sm break-keep text-muted-foreground">
          고치는 사이 이 장이 바뀌어 이대로는 저장할 수 없어요. 쓴 글을 복사해 두고 취소한 뒤, 최신 글에서 문단을 다시
          골라 주세요.
        </p>
      )}
      {hasPendingAiEdits && (
        <p id={`${id}-pending`} className="text-sm break-keep text-muted-foreground">
          저장하면 이 장에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          취소
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          aria-disabled={isSaving}
          aria-describedby={hasPendingAiEdits ? `${id}-pending` : undefined}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (isSaving) return;
            onSave();
          }}
        >
          {isSaving ? "저장 중…" : "저장"}
        </Button>
      </div>
    </div>
  );
}
