import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { History, RefreshCw, TriangleAlert } from "lucide-react";
import { useForm, useWatch } from "react-hook-form";

import { useChatRoomMemoryQuery, type ChatRoomMemory } from "@/entities/chat-room";
import { CloverIcon, useCloverPricingQuery } from "@/entities/clover";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import {
  useClearMemoryNoteMutation,
  useRevertMemorySummaryMutation,
  useSaveMemoryNoteMutation,
  useSaveMemorySummaryMutation,
} from "../api/memoryMutations";
import { toNoteRequest, toSummaryRequest } from "../model/formToServer";
import { toMemoryWriteError, type MemoryWriteError } from "../model/memoryWriteError";
import { isNoteSaveBlocked } from "../model/noteSaveGuard";
import { browserStorage, isRollbackUnseen, readSeenRollback, writeSeenRollback } from "../model/rollbackNotice";
import { countMemoryChars, createMemoryFormSchema, memoryFormOptions, type MemoryFormValues } from "../model/schema";
import { serverToForm } from "../model/serverToForm";
import { isSummaryRegenerateOffered } from "../model/regenerateOffer";
import { summaryFoldingCopy } from "../model/summaryFoldingCopy";
import { summaryRevertHint } from "../model/summaryRevertHint";
import { RegenerateSummaryModal } from "./RegenerateSummaryModal";

type RoomMemoryEditorProps = {
  roomId: string;
  /** 노트 비우기 확인. 확인 모달은 다른 feature(`manage-chat-room`)라 위젯이 주입한다 — 확인되면 `clear`를
   * 부른다(`clear`는 던지지 않는다). */
  onClearNoteRequest: (clear: () => Promise<void>) => Promise<void>;
  /** 바뀔 때마다 요약 편집을 연다(요약이 있고 아직 편집 중이 아니면). 패널의 다른 탭이 "요약 고치기"로 이 칸에 넘겨줄 때 쓴다 —
   * 값 자체는 뜻이 없고 바뀌었다는 것만 본다. 주지 않으면 아무 일도 없다. */
  editSummaryRequest?: number;
};

type WriteErrorState = { section: "summary" | "note"; error: MemoryWriteError };

const SOURCE_LABEL: Record<NonNullable<ChatRoomMemory["summary"]>["source"], string> = {
  auto: "AI가 정리함",
  user: "직접 고침",
};

/** 기억 노트 패널의 본문. lg 인라인 패널과 lg 미만 Dialog가 같은 본문을 쓴다(제목은 각 컨테이너가 든다). */
export function RoomMemoryEditor({ roomId, onClearNoteRequest, editSummaryRequest }: RoomMemoryEditorProps) {
  const memoryQuery = useChatRoomMemoryQuery(roomId);

  if (memoryQuery.isPending) {
    return <p className="py-6 text-center text-sm text-muted-foreground">불러오는 중…</p>;
  }
  if (!memoryQuery.data) {
    return (
      <div className="flex flex-col items-center gap-3 py-6">
        <p className="text-sm break-keep text-muted-foreground">기억 노트를 불러오지 못했어요.</p>
        <Button type="button" variant="outline" className="hover:bg-secondary" onClick={() => void memoryQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }
  return (
    // 방마다 폼을 새로 만든다 — 패널을 연 채 다른 방으로 가면 이전 방의 노트가 기준값으로 남아 새 방에
    // 저장될 수 있다.
    <RoomMemoryForm
      key={roomId}
      roomId={roomId}
      memory={memoryQuery.data}
      onReload={async () => {
        await memoryQuery.refetch();
      }}
      onClearNoteRequest={onClearNoteRequest}
      editSummaryRequest={editSummaryRequest}
    />
  );
}

type RoomMemoryFormProps = {
  roomId: string;
  memory: ChatRoomMemory;
  onReload: () => Promise<void>;
  onClearNoteRequest: RoomMemoryEditorProps["onClearNoteRequest"];
  editSummaryRequest: RoomMemoryEditorProps["editSummaryRequest"];
};

function RoomMemoryForm({ roomId, memory, onReload, onClearNoteRequest, editSummaryRequest }: RoomMemoryFormProps) {
  const fieldId = useId();
  const schema = useMemo(() => createMemoryFormSchema(memory.limits), [memory.limits]);
  // 기준값은 처음 한 번만 굳힌다 — 편집 중에 새 요약이 도착해도(턴 뒤 리페치) 입력을 덮지 않는다.
  const form = useForm<MemoryFormValues>({ ...memoryFormOptions(schema), defaultValues: serverToForm(memory) });
  const { errors, isSubmitting } = form.formState;
  const noteLength = countMemoryChars(useWatch({ control: form.control, name: "note" }));
  const summaryLength = countMemoryChars(useWatch({ control: form.control, name: "summary" }));

  const saveNoteMutation = useSaveMemoryNoteMutation(roomId);
  const clearNoteMutation = useClearMemoryNoteMutation(roomId);
  const saveSummaryMutation = useSaveMemorySummaryMutation(roomId);
  const revertMutation = useRevertMemorySummaryMutation(roomId);

  const [isEditingSummary, setIsEditingSummary] = useState(false);
  // 요약 편집은 [고치기]를 누른 시점의 버전으로 저장한다 — 그사이 요약이 새로 접혔으면 서버가 409로 막는다.
  const [editBaseVersion, setEditBaseVersion] = useState(memory.version);
  const [writeError, setWriteError] = useState<WriteErrorState | undefined>(undefined);
  const [announcement, setAnnouncement] = useState("");
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const noteRef = useRef<HTMLTextAreaElement | null>(null);
  const shouldFocusEditButtonRef = useRef(false);

  // 되감기 알림: 롤백 한 번에 한 번. 패널이 열려 있는 동안 롤백이 일어나도(메시지 삭제 등) 잡는다.
  const [shownRollbackAt, setShownRollbackAt] = useState<string | undefined>(undefined);
  useEffect(() => {
    const storage = browserStorage();
    const rolledBackAt = memory.rolledBackAt;
    if (rolledBackAt === undefined || !isRollbackUnseen(rolledBackAt, readSeenRollback(storage, roomId))) return;
    setShownRollbackAt(rolledBackAt);
    writeSeenRollback(storage, roomId, rolledBackAt);
  }, [memory.rolledBackAt, roomId]);

  // 패널이 열린 채 요약이 바뀌면 스크린리더에 알린다. 바뀐 까닭은 새 접기만이 아니라 되감기 롤백·다른 탭의
  // 고침일 수도 있어 까닭을 말하지 않는다. 이 패널에서 저장·되돌리기한 결과는 그 자리에서 따로 알리므로
  // 건너뛴다.
  const summaryUpdatedAt = memory.summary?.updatedAt;
  const lastSummaryUpdatedAtRef = useRef(summaryUpdatedAt);
  const isOwnWriteRef = useRef(false);
  useEffect(() => {
    if (summaryUpdatedAt === lastSummaryUpdatedAtRef.current) return;
    lastSummaryUpdatedAtRef.current = summaryUpdatedAt;
    if (isOwnWriteRef.current) {
      isOwnWriteRef.current = false;
      return;
    }
    setAnnouncement(summaryUpdatedAt ? "요약이 바뀌었어요." : "요약이 비었어요.");
  }, [summaryUpdatedAt]);

  // [저장]·[취소]로 편집 칸이 사라지면 포커스가 `<body>`로 떨어진다 — 다시 나타난 [고치기]로 돌린다.
  useEffect(() => {
    if (isEditingSummary || !shouldFocusEditButtonRef.current) return;
    shouldFocusEditButtonRef.current = false;
    editButtonRef.current?.focus();
  }, [isEditingSummary]);

  function handleStartSummaryEdit() {
    form.resetField("summary", { defaultValue: memory.summary?.text ?? "" });
    setEditBaseVersion(memory.version);
    setWriteError(undefined);
    setIsEditingSummary(true);
  }

  // 다른 탭의 "요약 고치기". 요청 값이 바뀐 렌더에서만 한 번 연다 — 같은 요청으로 편집을 닫은 뒤 다시 열리지 않게.
  const handledEditRequestRef = useRef(editSummaryRequest);
  useEffect(() => {
    if (editSummaryRequest === handledEditRequestRef.current) return;
    handledEditRequestRef.current = editSummaryRequest;
    if (memory.summary === undefined || isEditingSummary) return;
    form.resetField("summary", { defaultValue: memory.summary.text });
    setEditBaseVersion(memory.version);
    setWriteError(undefined);
    setIsEditingSummary(true);
  }, [editSummaryRequest, form, isEditingSummary, memory.summary, memory.version]);

  function stopSummaryEdit() {
    // 두 칸의 저장이 폼 전체를 검증하므로, 닫은 편집 칸에 상한을 넘긴 값이 남으면 보이지 않는 오류가 노트
    // 저장을 막는다 — 기준값으로 되돌린다(오류도 함께 풀린다).
    form.resetField("summary");
    shouldFocusEditButtonRef.current = true;
    setIsEditingSummary(false);
  }

  function handleCancelSummaryEdit() {
    stopSummaryEdit();
  }

  async function handleReloadAfterConflict() {
    await onReload();
    setWriteError(undefined);
    if (isEditingSummary) stopSummaryEdit();
  }

  // 저장이 검증에 걸리면(422) 오류를 칸에 붙인다 — 서버가 칸을 알려 주지 않으면 저장한 칸이다. 그 밖의
  // 실패는 칸 위 알림으로 보인다.
  function showSaveError(section: WriteErrorState["section"], error: MemoryWriteError) {
    if (error.kind === "invalid") {
      form.setError(error.field ?? section, { message: error.message });
      return;
    }
    setWriteError({ section, error });
  }

  async function handleSaveSummary(values: MemoryFormValues) {
    setWriteError(undefined);
    try {
      isOwnWriteRef.current = true;
      const next = await saveSummaryMutation.mutateAsync(toSummaryRequest(values, editBaseVersion));
      form.resetField("summary", { defaultValue: next.summary?.text ?? "" });
      setAnnouncement("요약을 고쳤어요. 다음 대화부터 반영돼요.");
      stopSummaryEdit();
    } catch (error) {
      isOwnWriteRef.current = false;
      showSaveError("summary", toMemoryWriteError(error));
    }
  }

  async function handleRevert() {
    if (revertMutation.isPending || !memory.summary?.canRevert) return;
    setWriteError(undefined);
    try {
      isOwnWriteRef.current = true;
      await revertMutation.mutateAsync(memory.version);
      setAnnouncement("고치기 전 요약으로 되돌렸어요.");
    } catch (error) {
      isOwnWriteRef.current = false;
      setWriteError({ section: "summary", error: toMemoryWriteError(error) });
    }
  }

  async function handleRegenerate() {
    setWriteError(undefined);
    // 다시 만든 요약은 이 자리에서 따로 알리므로, 패널이 열린 동안의 요약 갱신 알림은 건너뛴다.
    isOwnWriteRef.current = true;
    const isRegenerated = await RegenerateSummaryModal.call({ roomId });
    if (isRegenerated) {
      setAnnouncement("요약을 다시 만들었어요. 다음 대화부터 반영돼요.");
    } else {
      isOwnWriteRef.current = false;
    }
  }

  async function handleSaveNote(values: MemoryFormValues) {
    setWriteError(undefined);
    try {
      const next = await saveNoteMutation.mutateAsync(toNoteRequest(values));
      form.resetField("note", { defaultValue: next.note });
      setAnnouncement("저장했어요. 다음 대화부터 반영돼요.");
    } catch (error) {
      showSaveError("note", toMemoryWriteError(error));
    }
  }

  async function handleClearNote() {
    await onClearNoteRequest(async () => {
      setWriteError(undefined);
      try {
        const next = await clearNoteMutation.mutateAsync();
        form.resetField("note", { defaultValue: next.note });
        setAnnouncement("꼭 기억할 것을 비웠어요.");
      } catch (error) {
        setWriteError({ section: "note", error: toMemoryWriteError(error) });
      }
    });
    // 확인 모달은 앱 루트에 마운트돼 닫힌 뒤 포커스를 돌려주지 않는다 — 비운 칸으로 직접 옮긴다.
    noteRef.current?.focus();
  }

  const summaryId = `${fieldId}-summary`;
  const noteId = `${fieldId}-note`;
  const revertHintId = `${fieldId}-revert-hint`;
  const summary = memory.summary;
  // 요약 다시 만들기는 장면·사실 목록과 같은 서버 스위치 뒤에 있다. 버튼은 요약 접기가 꺼진 방에서도 숨기지만(쓰이지 않는
  // 요약에 클로버를 쓰게 하지 않으려고) 되돌리기 안내는 라우트가 열려 있는 한 바뀐 문장이다 — 앞서 다시 만든 요약은 접기가
  // 꺼진 뒤에도 되돌릴 수 있다.
  const isRegenerateOpen = memory.features.itemsVisible;
  const isRegenerateOffered = isSummaryRegenerateOffered(memory.features);
  const foldingCopy = summaryFoldingCopy(memory.features.summaryFolding);
  // 편집 중에 요약이 사라질 수 있다(다른 탭에서 초기화) — 그때는 편집 칸도 [저장]도 없다.
  const isSummaryEditOpen = isEditingSummary && summary !== undefined;
  const noteField = form.register("note");
  const isNoteSaving = saveNoteMutation.isPending || clearNoteMutation.isPending;
  // [저장]의 비활성 표시와 클릭 가드가 이 값 하나를 본다.
  const isNoteSaveDisabled = isNoteSaveBlocked({
    isSavePending: saveNoteMutation.isPending,
    isClearPending: clearNoteMutation.isPending,
    isSubmitting,
  });

  let summaryBody: ReactNode;
  if (summary === undefined) {
    // 첫 접기 전에는 고칠 요약이 없다(요약은 대화가 충분히 쌓여야 처음 만들어진다).
    summaryBody = (
      <p className="rounded-lg border border-dashed border-border px-3.5 py-3 text-sm break-keep text-muted-foreground">
        {foldingCopy.emptySummary}
      </p>
    );
  } else if (isEditingSummary) {
    summaryBody = (
      <div className="flex flex-col gap-1.5">
        {/* 글만큼 자라되 상한에서 멈추고 칸 안에서 스크롤한다 — 상한이 없으면 긴 요약에서 칸 아래 글자 수·[저장]이 작은 화면
            밖으로 밀려난다. */}
        <Textarea
          id={summaryId}
          rows={8}
          className="max-h-80"
          autoFocus
          aria-label="지금까지의 이야기"
          aria-invalid={!!errors.summary}
          aria-describedby={errors.summary ? `${summaryId}-error ${summaryId}-count` : `${summaryId}-count`}
          {...form.register("summary")}
        />
        <CharacterCount id={`${summaryId}-count`} count={summaryLength} max={memory.limits.summaryMaxLength} />
        {errors.summary && (
          <p id={`${summaryId}-error`} role="alert" className="text-xs text-destructive-text">
            {errors.summary.message}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" className="hover:bg-secondary" onClick={handleCancelSummaryEdit}>
            취소
          </Button>
          <Button
            type="button"
            aria-disabled={isSubmitting}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (!isSubmitting) void form.handleSubmit(handleSaveSummary)();
            }}
          >
            {saveSummaryMutation.isPending ? "저장 중..." : "저장"}
          </Button>
        </div>
      </div>
    );
  } else {
    summaryBody = (
      <div className="flex flex-col gap-3">
        <p className="text-sm break-keep break-words whitespace-pre-wrap text-foreground">
          {summary.text || <span className="text-muted-foreground">비어 있어요.</span>}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button ref={editButtonRef} type="button" variant="outline" className="hover:bg-secondary" onClick={handleStartSummaryEdit}>
            고치기
          </Button>
          <Button
            type="button"
            variant="ghost"
            aria-disabled={!summary.canRevert || revertMutation.isPending}
            aria-describedby={revertHintId}
            className="hover:bg-secondary aria-disabled:opacity-65"
            onClick={() => void handleRevert()}
          >
            되돌리기
          </Button>
          {isRegenerateOffered && <RegenerateSummaryButton onClick={() => void handleRegenerate()} />}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* 노트가 어디까지 따라가는지 먼저 말한다 — 새 대화방이나 대화 프로필에 묶여 있다고 오해하면 같은 내용을 다시 적거나
          프로필을 바꾸면 지워질 거라 여긴다. 아래 두 칸 모두에 걸리는 말이라 칸 밖 맨 위에 둔다. */}
      <p className="text-xs break-keep text-muted-foreground">
        새 대화방에는 이어지지 않고, 대화 프로필을 바꿔도 그대로예요.
      </p>

      <section aria-labelledby={`${summaryId}-heading`} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
          <h3 id={`${summaryId}-heading`} className="text-sm font-semibold text-foreground">
            지금까지의 이야기
          </h3>
          {summary && (
            <span className="text-xs text-muted-foreground">
              {SOURCE_LABEL[summary.source]} ·{" "}
              <time dateTime={summary.updatedAt}>{formatRelativeTime(summary.updatedAt, new Date())}</time>
            </span>
          )}
        </div>

        {shownRollbackAt !== undefined && (
          <p className="flex gap-2 rounded-lg border border-border px-3.5 py-2.5 text-xs break-keep text-foreground">
            <History aria-hidden className="mt-px size-3.5 shrink-0 text-muted-foreground" />
            지난 대화가 바뀌어서 요약이 이전 판으로 돌아갔어요.
          </p>
        )}

        {writeError?.section === "summary" && (
          <WriteErrorNotice error={writeError.error} onReload={() => void handleReloadAfterConflict()} />
        )}

        {summaryBody}

        <ul className="flex flex-col gap-1 text-xs break-keep text-muted-foreground">
          <li>{foldingCopy.foldingHint}</li>
          <li>지난 대화가 바뀌면(고치기·지우기·다시 생성·방금 전 답변으로) 그 뒤의 요약은 직접 고친 내용까지 이전 요약으로 돌아가요.</li>
          {summary && (
            <li id={revertHintId}>{summaryRevertHint(isRegenerateOpen)}</li>
          )}
        </ul>
      </section>

      <section aria-labelledby={`${noteId}-heading`} className="flex flex-col gap-1.5 border-t border-border pt-5">
        <label id={`${noteId}-heading`} htmlFor={noteId} className="text-sm font-semibold text-foreground">
          꼭 기억할 것
        </label>
        {writeError?.section === "note" && (
          <WriteErrorNotice error={writeError.error} onReload={() => void handleReloadAfterConflict()} />
        )}
        {/* 요약 칸과 같은 이유로 상한을 둔다(상한까지 다 채우면 390px 폭 시트에서 칸 하나가 화면 높이를 넘었다). */}
        <Textarea
          id={noteId}
          rows={5}
          className="max-h-60"
          placeholder="캐릭터가 이 대화방에서 잊지 않았으면 하는 것"
          aria-invalid={!!errors.note}
          aria-describedby={errors.note ? `${noteId}-error ${noteId}-count` : `${noteId}-count`}
          {...noteField}
          ref={(element) => {
            noteField.ref(element);
            noteRef.current = element;
          }}
        />
        <CharacterCount
          id={`${noteId}-count`}
          count={noteLength}
          max={memory.limits.noteMaxLength}
          help="다음 대화부터 반영돼요. 실명 등 개인정보는 적지 않는 것을 권해요."
        />
        {errors.note && (
          <p id={`${noteId}-error`} role="alert" className="text-xs text-destructive-text">
            {errors.note.message}
          </p>
        )}
        <div className="mt-1.5 flex justify-between gap-2">
          <Button
            type="button"
            variant="ghost"
            aria-disabled={isNoteSaving}
            className="hover:bg-secondary aria-disabled:opacity-65"
            onClick={() => {
              if (!isNoteSaving) void handleClearNote();
            }}
          >
            비우기
          </Button>
          {/* 화면에서 채움 버튼은 하나만 — 요약을 고치는 동안은 그쪽 [저장]이 지금 누를 것이다. */}
          <Button
            type="button"
            variant={isSummaryEditOpen ? "outline" : "default"}
            aria-disabled={isNoteSaveDisabled}
            className={cn("aria-disabled:opacity-65", isSummaryEditOpen && "hover:bg-secondary")}
            onClick={() => {
              if (!isNoteSaveDisabled) void form.handleSubmit(handleSaveNote)();
            }}
          >
            {saveNoteMutation.isPending ? "저장 중..." : "저장"}
          </Button>
        </div>
      </section>

      {/* 저장·되돌리기 결과와 패널이 열린 동안의 요약 갱신을 한 곳에서 알린다. 조건부로 마운트하면 알림 여부가
          갈리므로 늘 둔다(빈 문자열이면 아무것도 안 보인다). */}
      <p aria-live="polite" className="text-xs break-keep text-muted-foreground empty:hidden">
        {announcement}
      </p>
    </div>
  );
}

/** 요약 다시 만들기 버튼. 값을 받기 전에는 가격을 빼고 그린다(확인 대화가 가격을 다시 보인다). 화면의 유일한 채움 버튼은
 * 노트 [저장]이라 이 버튼은 윤곽이다. */
function RegenerateSummaryButton({ onClick }: { onClick: () => void }) {
  const cost = useCloverPricingQuery().data?.memorySummaryRegenerateCost;
  return (
    <Button type="button" variant="outline" className="hover:bg-secondary" onClick={onClick}>
      <RefreshCw aria-hidden className="size-4" />
      다시 만들기
      {cost !== undefined && (
        <>
          <span aria-hidden className="inline-flex items-center gap-1 text-muted-foreground tabular-nums">
            <CloverIcon />
            {cost.toLocaleString()}
          </span>
          <span className="sr-only">(클로버 {cost.toLocaleString()}개)</span>
        </>
      )}
    </Button>
  );
}

function WriteErrorNotice({ error, onReload }: { error: MemoryWriteError; onReload: () => void }) {
  if (error.kind !== "stale") {
    return (
      <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
        {error.message}
      </p>
    );
  }
  // 입력은 그대로 둔다 — 다시 불러오기를 누를 때까지 사용자가 쓴 내용을 지우지 않는다.
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3.5 py-2.5">
      <span className="flex items-center gap-2 text-xs break-keep text-foreground">
        <TriangleAlert aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
        {error.message}
      </span>
      <Button type="button" variant="outline" size="sm" className="hover:bg-secondary" onClick={onReload}>
        다시 불러오기
      </Button>
    </div>
  );
}
