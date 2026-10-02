import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { useEffect, useRef, useState } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import { focusNeighborToggle, itemOpenKey, useBuilderUiState } from "@/features/build-common";
import {
  createKeywordNote,
  dragMoveIndices,
  MAX_ALWAYS_ON_KEYWORD_NOTES,
  MAX_KEYWORD_NOTES,
  stepMoveIndices,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

import { KeywordNoteCard, keywordNoteHandleId } from "./KeywordNoteCard";

const KEYWORD_NOTE_LIST: StoryCollapsibleList = "keywordNote";
const ADD_BUTTON_ID = "keyword-note-add";
const ADD_LIMIT_REASON_ID = "keyword-note-add-limit";

// dnd-kit 기본 안내는 영어이고 Space 로 집는 키보드 센서를 전제한다. 이 목록은 포인터로만 끌고 키보드는 핸들의
// 화살표 키로 한 칸씩 옮기므로 그 방법을 한국어로 알려 준다.
const SCREEN_READER_INSTRUCTIONS = {
  draggable: "위·아래 화살표 키로 노트를 한 칸씩 옮길 수 있어요. 위에 있을수록 먼저 실려요.",
};

/** 탭 전체가 선택사항(0개도 발행 가능). 목록 순서가 곧 우선순위라 드래그·화살표 키로 재정렬한다. */
export function KeywordNoteTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    control,
    getValues,
    formState: { errors },
  } = form;
  const { fields, append, remove, move } = useFieldArray({ control, name: "keywordNotes" });
  const uiState = useBuilderUiState();
  const startingSetups = useWatch({ control, name: "startingSetups" });
  // 상시 개수만 따로 구독한다 — 노트 배열 전체를 구독하면 아무 노트에 한 글자 칠 때마다 카드 50개가 다시 그려진다.
  const alwaysOnFlags = useWatch({
    control,
    name: fields.map((_, index) => `keywordNotes.${index}.alwaysOn` as const),
  });
  const alwaysOnCount = alwaysOnFlags.filter(Boolean).length;
  const sensors = useSensors(useSensor(PointerSensor));
  const [announcement, setAnnouncement] = useState("");
  // 재정렬 뒤 포커스를 둘 요소. 렌더가 끝난 뒤에야 그 요소가 제자리에 있으므로 effect 에서 옮긴다.
  const pendingFocusIdRef = useRef<string | undefined>(undefined);
  // 배열 자체의 위반(노트 수·상시 수 상한)이 담기는 자리는 탭 마운트 상태에 따라 `.message` 와 `.root.message` 로
  // 갈린다(StartingSetupTab 의 같은 자리 주석 참고). 둘 다 읽는다.
  const notesError = errors.keywordNotes?.message ?? errors.keywordNotes?.root?.message;
  const isFull = fields.length >= MAX_KEYWORD_NOTES;

  useEffect(() => {
    const targetId = pendingFocusIdRef.current;
    if (!targetId) return;
    pendingFocusIdRef.current = undefined;
    document.getElementById(targetId)?.focus();
  }, [fields]);

  // 드래그 끝의 안내는 dnd-kit 이 `announcements` 로 따로 읽으므로 여기서는 화살표 키 이동만 알린다.
  function handleStep(index: number, step: -1 | 1, fieldId: string) {
    const indices = stepMoveIndices(index, step, fields.length);
    if (!indices) return;
    move(indices.from, indices.to);
    pendingFocusIdRef.current = keywordNoteHandleId(fieldId);
    setAnnouncement(`${indices.to + 1}번째로 옮겼어요.`);
  }

  function handleDragEnd({ active, over }: DragEndEvent) {
    const indices = dragMoveIndices(
      fields.map((field) => field.id),
      String(active.id),
      over ? String(over.id) : null,
    );
    if (indices) move(indices.from, indices.to);
  }

  function handleRemove(index: number) {
    // 지운 자리의 다음 노트(없으면 앞 노트, 그것도 없으면 추가 버튼)의 머리 줄 토글로 포커스를 옮긴다 — 삭제 버튼이
    // 사라지며 포커스가 body 로 떨어지면 키보드 사용자가 처음부터 다시 Tab 해야 한다. 이웃 토글은 지우기 전에도 화면에
    // 있으므로 지우기 전에 옮긴다.
    const keys = getValues("keywordNotes").map((note) => itemOpenKey(KEYWORD_NOTE_LIST, note.id));
    focusNeighborToggle(keys, index, document.getElementById(ADD_BUTTON_ID));
    remove(index);
    setAnnouncement("노트를 삭제했어요.");
  }

  function handleAdd() {
    // 51번째 노트는 서버가 저장을 거절해 그 초안의 자동저장 전체가 멈추므로 폼에 들어가지 않게 한다.
    if (isFull) return;
    const id = crypto.randomUUID();
    // 새 노트를 열림으로 기록하는 일은 append 와 같은 핸들러에서 그보다 먼저 한다. 같은 커밋에 본문이 보여야 append 가
    // 주는 포커스가 숨은 입력칸에 걸려 헛돌지 않는다.
    uiState.open([itemOpenKey(KEYWORD_NOTE_LIST, id)]);
    append(createKeywordNote(id), { focusName: `keywordNotes.${fields.length}.name` });
  }

  const announcements: Announcements = {
    onDragStart: () => undefined,
    onDragOver: () => undefined,
    onDragCancel: () => "옮기기를 취소했어요.",
    onDragEnd: ({ over }) => {
      const to = over ? fields.findIndex((field) => field.id === over.id) : -1;
      return to === -1 ? undefined : `${to + 1}번째로 옮겼어요.`;
    },
  };

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <Label>키워드북</Label>
          <p className="text-xs tabular-nums text-muted-foreground">
            노트 {fields.length} / {MAX_KEYWORD_NOTES} · 상시 {alwaysOnCount} / {MAX_ALWAYS_ON_KEYWORD_NOTES}
          </p>
        </div>
        <p className="text-sm break-keep text-muted-foreground">
          대화에 키워드가 나오면 그 노트의 정보를 AI에게 함께 보내요. 직전 AI 응답과 이번 메시지에서 찾고, 영문
          대소문자는 구분하지 않아요. 등록하지 않아도 발행할 수 있어요.
        </p>
        <p className="text-sm break-keep text-muted-foreground">
          한 턴에 키워드로 열리는 노트는 <span className="font-medium text-foreground">위에서부터 5개</span>까지예요.
          넘치면 아래 노트가 빠지니 중요한 노트를 위로 올려 주세요.
        </p>
        <details className="group rounded-xl border border-border px-4 py-3">
          <summary className="cursor-pointer rounded-md text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            동작과 작성 요령
          </summary>
          <ul className="mt-3 flex list-disc flex-col gap-1.5 pl-5 text-sm break-keep text-muted-foreground marker:text-muted-foreground">
            <li>
              상시 노트는 최대 {MAX_ALWAYS_ON_KEYWORD_NOTES}개예요. 키워드 없이 매 턴 실리고, 위의 5개와 따로 세요.
            </li>
            <li>
              금지 키워드가 이번 대화(직전 AI 응답·이번 메시지)에 나오면 그 노트는 유지 중이든 상시든 이번 턴엔 빠져요.
            </li>
            <li>
              AI가 말한 단어도 노트를 열어요. 노트가 실려 AI가 그 키워드를 말하면 다음 턴에도 다시 열려요 — 끊고
              싶으면 금지 키워드를 넣어 주세요.
            </li>
            <li>정보에 대상의 이름을 적어 주세요. 노트 이름은 목록에서만 보이고 AI에게는 보내지 않아요.</li>
            <li>같은 대상을 부르는 동의어·별명도 키워드로 넣어 주세요.</li>
            <li>
              한두 글자의 흔한 단어는 피해 주세요. 글자 일부만 맞아도 열려서 &ldquo;눈&rdquo;은 &ldquo;눈물&rdquo;에도
              걸려요.
            </li>
          </ul>
        </details>
        {!!notesError && (
          <p role="alert" className="text-xs text-destructive-text">
            {notesError}
          </p>
        )}
      </div>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 키워드 노트가 없어요.</p>
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
          accessibility={{ announcements, screenReaderInstructions: SCREEN_READER_INSTRUCTIONS }}
        >
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <ol className="flex flex-col gap-4" aria-label="키워드 노트 목록(위에 있을수록 먼저 실려요)">
              {fields.map((field, index) => (
                <KeywordNoteCard
                  key={field.id}
                  id={field.id}
                  index={index}
                  startingSetups={startingSetups}
                  isAlwaysOnFull={alwaysOnCount >= MAX_ALWAYS_ON_KEYWORD_NOTES}
                  onRemove={() => handleRemove(index)}
                  onStep={(step) => handleStep(index, step, field.id)}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
      )}

      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>

      <div className="flex flex-col gap-1.5">
        {/* 상한에서도 버튼을 남기고 `aria-disabled` 로 잠근다 — 지우면 왜 더 못 만드는지가 사라지고, `disabled` 는
            포커스를 body 로 떨어뜨린다. 실제 차단은 handleAdd 다. */}
        <Button
          id={ADD_BUTTON_ID}
          type="button"
          variant="secondary"
          className="w-fit aria-disabled:pointer-events-none aria-disabled:opacity-65"
          aria-disabled={isFull}
          aria-describedby={isFull ? ADD_LIMIT_REASON_ID : undefined}
          onClick={handleAdd}
        >
          노트 추가
        </Button>
        {isFull && (
          <p id={ADD_LIMIT_REASON_ID} className="text-xs text-muted-foreground">
            노트는 최대 {MAX_KEYWORD_NOTES}개까지 만들 수 있어요. 더 넣으려면 쓰지 않는 노트를 지워 주세요.
          </p>
        )}
      </div>
    </div>
  );
}
