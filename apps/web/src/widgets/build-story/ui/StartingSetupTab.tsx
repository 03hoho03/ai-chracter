import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { X } from "lucide-react";
import { useRef, useState } from "react";
import { useFieldArray, useFormContext, useWatch } from "react-hook-form";

import { MAX_STARTING_SETUPS, MAX_SUGGESTED_REPLIES } from "@/entities/content";
import {
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemDragHandle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderUiState,
} from "@/features/build-common";
import {
  FieldLabelText,
  reconcileKeywordNotesOnStartingSetupRemoval,
  startingSetupSummary,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";
import { MediaBookConfirmModal } from "@/features/edit-media-book";

import { MediaTagInsertButton } from "./MediaTagInsertButton";
import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";
import { StoryMacroNotice } from "./StoryMacroNotice";
import { UnknownMediaTagNotice } from "./UnknownMediaTagNotice";

/** 열림 키의 목록 이름 — 발행 실패 때 셸이 오류 항목을 여는 키와 같은 이름이어야 한다(타입이 목록 정의의 키로 묶는다). */
const STARTING_SETUP_LIST: StoryCollapsibleList = "startingSetup";

/** "설정 추가"로 여러 시작설정 생성, 발행하려면 최소 1개 필요.
 * 그 최소 1개는 storyBuilderSchema의 `.min(1)`이 막고, 위반은 발행을 눌렀을 때 토스트와 탭 에러로
 * 드러난다 — 발행 버튼 자체는 비활성화하지 않는다(apps/web/CLAUDE.md §폼 / 빌더). */
export function StartingSetupTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    control,
    getValues,
    setValue,
    formState: { errors },
  } = form;
  const { fields, append, remove, move } = useFieldArray({ control, name: "startingSetups" });
  const sensors = useSensors(useSensor(PointerSensor));
  const uiState = useBuilderUiState();
  const addButtonRef = useRef<HTMLButtonElement>(null);

  // 지운 시작설정 자리에서 포커스를 다음 시작설정의 머리 줄로(없으면 이전, 그것도 없으면 설정 추가 버튼으로) 옮긴다. `keys`
  // 는 지우기 전 목록이다 — 이웃의 머리 줄은 지운 뒤에도 남는다. 상한(4개)에서는 추가 버튼이 없지만 그때는 이웃이 늘 있다.
  function focusAfterRemoval(keys: readonly string[], index: number) {
    focusNeighborToggle(keys, index, addButtonRef.current);
  }

  // 시작설정 하나가 그 아래 스탯·엔딩을 통째로 품으므로, 그것들이 있으면 몇 개가 함께 사라지는지 먼저 묻는다. 비어 있는
  // 시작설정은 묻지 않고 지운다. 취소하면 아무것도 바꾸지 않는다.
  async function handleRemove(index: number) {
    const setups = getValues("startingSetups");
    const removed = setups[index];
    if (removed === undefined) return;
    const keys = setups.map((setup) => itemOpenKey(STARTING_SETUP_LIST, setup.id));
    const trigger = document.activeElement;
    const contents = [
      removed.stats.length > 0 ? `스탯 ${removed.stats.length}개` : undefined,
      removed.endings.length > 0 ? `엔딩 ${removed.endings.length}개` : undefined,
    ].filter((part) => part !== undefined);

    if (contents.length > 0) {
      const isConfirmed = await MediaBookConfirmModal.call({
        title: "시작설정을 지울까요?",
        description: `이 시작설정의 ${contents.join("와 ")}도 함께 지워져요.`,
        confirmLabel: "지우기",
        // 취소면 삭제 버튼으로, 지웠으면 그 카드가 사라지므로 이웃 시작설정의 머리 줄(없으면 설정 추가 버튼)로.
        onRestoreFocus: () => {
          if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
          else focusAfterRemoval(keys, index);
        },
      });
      if (!isConfirmed) return;
    } else {
      // 묻지 않는 경로는 지우기 전에 옮긴다 — 지운 뒤로 미루면 누른 삭제 버튼이 사라지며 포커스가 body 로 떨어진다.
      focusAfterRemoval(keys, index);
    }

    setValue(
      "keywordNotes",
      reconcileKeywordNotesOnStartingSetupRemoval(getValues("keywordNotes"), removed.id),
      { shouldDirty: true },
    );
    remove(index);
  }

  // 새 시작설정은 펼친 채 이름 칸에 포커스한다. 열림 기록은 `append` 와 같은 핸들러에서 먼저 해야 새 본문이 보이는 채로
  // 커밋된다. 포커스 칸을 이름으로 못 박는 이유: 지정하지 않으면 RHF 는 그 항목에서 먼저 등록된 칸으로 보내는데, 시작설정은
  // "이미지 넣기"용 ref 때문에 프롤로그가 먼저 등록된다.
  function handleAdd() {
    const id = crypto.randomUUID();
    uiState.open([itemOpenKey(STARTING_SETUP_LIST, id)]);
    append(
      {
        id,
        name: "",
        prologue: "",
        openingSituation: "",
        playGuide: "",
        suggestedReplies: [],
        stats: [],
        endings: [],
        situationNotes: [],
      },
      { focusName: `startingSetups.${fields.length}.name` },
    );
  }

  function handleDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const oldIndex = fields.findIndex((field) => field.id === active.id);
    const newIndex = fields.findIndex((field) => field.id === over.id);
    if (oldIndex !== -1 && newIndex !== -1) move(oldIndex, newIndex);
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1" data-field-path="startingSetups">
        <Label><FieldLabelText field="startingSetups" /></Label>
        <p className="text-sm text-muted-foreground">
          여러 개의 시작 상황을 만들 수 있어요. 목록의 첫 번째 항목이 기본 선택이에요.
        </p>
        {/* 배열 자체의 위반(`.max(4)`)이 담기는 자리가 마운트 상태에 따라 갈린다 —
            Radix TabsContent가 비활성 탭을 언마운트하므로, 이 탭을 열지 않고 발행하면
            `startingSetups`의 인덱스별 필드가 마운트돼 있지 않아 zodResolver가 그 필드 자체를 잎으로
            보고 `.message`에 담고, 이 탭이 이미 열려 있어 필드들이 마운트돼 있으면 `@hookform/resolvers`의
            isNameInFieldArray가 `startingSetups`를 필드배열로 판정해 배열 위반을 `.root.message`에
            담는다(같은 [발행] 버튼을 두 번 눌러 실측). 둘 다 읽어야 어느 경로로도 안내가 사라지지 않는다. */}
        {!!(errors.startingSetups?.message ?? errors.startingSetups?.root?.message) && (
          <p id="story-starting-setups-error" role="alert" className="text-xs text-destructive-text">
            {errors.startingSetups?.message ?? errors.startingSetups?.root?.message}
          </p>
        )}
      </div>

      {fields.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-10 text-center">
          <p className="text-sm text-muted-foreground">아직 등록된 시작설정이 없어요.</p>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={fields.map((field) => field.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-4">
              {fields.map((field, index) => (
                <StartingSetupRow
                  key={field.id}
                  id={field.id}
                  index={index}
                  onRemove={() => void handleRemove(index)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      {/* 상한에 닿으면 추가 버튼을 렌더하지 않는다(SettingTab의
          전개 예시와 같은 형태). 스키마의 `.max()`만으로는 발행 시점에야 막혀 5개째를 만들게 둔다. */}
      {fields.length < MAX_STARTING_SETUPS ? (
        <Button ref={addButtonRef} type="button" variant="secondary" className="w-fit" onClick={handleAdd}>
          설정 추가
        </Button>
      ) : null}
    </div>
  );
}

type StartingSetupRowProps = {
  id: string;
  index: number;
  onRemove: () => void;
};

/** 이름/프롤로그(필수), 시작상황(선택, 비어있으면 프롤로그가 첫
 * 메시지로 노출됨을 안내), 고급설정 뒤의 플레이가이드/추천 답변(선택). 목록 순서가 곧 기본 선택
 * 우선순위라 dnd-kit로 재정렬한다(AdvancedTab의 situationalImages와 동일 패턴). */
function StartingSetupRow({
  id,
  index,
  onRemove,
}: StartingSetupRowProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    setValue,
    getValues,
    formState: { errors },
  } = form;
  const rowErrors = errors.startingSetups?.[index];
  // 이 시작설정 아래 스탯·엔딩 오류도 같은 자리에 매달리지만 그 둘은 다른 탭 몫이라 머리 줄 오류 표시에서 뺀다.
  const hasOwnError =
    rowErrors !== undefined &&
    Object.entries(rowErrors).some(([key, value]) => key !== "stats" && key !== "endings" && value !== undefined);
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  // 머리 줄 열림 키·제목·요약 재료.
  const setupId = useWatch({ control, name: `startingSetups.${index}.id` });
  const name = useWatch({ control, name: `startingSetups.${index}.name` });
  const prologue = useWatch({ control, name: `startingSetups.${index}.prologue` });
  const suggestedReplies = useWatch({ control, name: `startingSetups.${index}.suggestedReplies` });
  const canAddSuggestedReply = suggestedReplies.length < MAX_SUGGESTED_REPLIES;
  const [replyInput, setReplyInput] = useState("");
  // "이미지 넣기"가 커서 자리를 읽을 입력창. `register` 의 ref 와 함께 건다.
  const prologueRef = useRef<HTMLTextAreaElement | null>(null);
  const openingSituationRef = useRef<HTMLTextAreaElement | null>(null);
  const prologueField = register(`startingSetups.${index}.prologue`);
  const openingSituationField = register(`startingSetups.${index}.openingSituation`);
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(
    () =>
      Boolean(getValues(`startingSetups.${index}.playGuide`)) ||
      getValues(`startingSetups.${index}.suggestedReplies`).length > 0,
  );

  function handleAddSuggestedReply() {
    const trimmed = replyInput.trim();
    // 상한 가드가 여기 있는 이유는 둘이다. (1) 입력칸이나
    // [추가] 버튼을 `disabled`로 막으면 그 속성이 붙는 순간 브라우저가 blur해 activeElement가
    // <body>로 떨어진다(apps/web/CLAUDE.md §포커스, WCAG 2.4.3). (2) `aria-disabled`는 포인터만
    // 막으므로(pointer-events-none) 키보드로 누른 Enter는 그대로 들어온다 — 실제 차단은 여기다
    // (GenerateImagesPromptField.tsx와 같은 레시피).
    if (!canAddSuggestedReply || !trimmed || suggestedReplies.includes(trimmed)) return;
    // 막힌 경우에는 사용자가 쓴 글을 지우지 않는다 — 상한에서 글자만 사라지면 피드백이 0이 된다.
    setReplyInput("");
    setValue(`startingSetups.${index}.suggestedReplies`, [...suggestedReplies, trimmed], {
      shouldDirty: true,
    });
  }

  function handleRemoveSuggestedReply(reply: string) {
    setValue(
      `startingSetups.${index}.suggestedReplies`,
      suggestedReplies.filter((item) => item !== reply),
      { shouldDirty: true },
    );
  }

  const trimmedName = name.trim();

  return (
    <CollapsibleItemCard
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      openKey={itemOpenKey(STARTING_SETUP_LIST, setupId)}
      title={name}
      placeholderTitle="새 시작설정"
      srTitlePrefix={`${index + 1}번째 시작설정: `}
      summary={startingSetupSummary({ prologue }, index)}
      hasError={hasOwnError}
      leading={<ItemDragHandle {...attributes} {...listeners} aria-label={`${index + 1}번째 시작설정 순서 변경`} />}
      trailing={
        <ItemRemoveButton
          label={trimmedName ? `${trimmedName} 시작설정 삭제` : `${index + 1}번째 시작설정 삭제`}
          onClick={onRemove}
        />
      }
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`starting-setup-${id}-name`}><FieldLabelText field="startingSetups.*.name" /></Label>
        <Input
          id={`starting-setup-${id}-name`}
          placeholder="시작설정 이름을 입력해주세요"
          aria-invalid={!!rowErrors?.name}
          aria-describedby={rowErrors?.name ? `starting-setup-${id}-name-error` : undefined}
          {...register(`startingSetups.${index}.name`)}
        />
        {rowErrors?.name && (
          <p id={`starting-setup-${id}-name-error`} role="alert" className="text-xs text-destructive-text">
            {rowErrors.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={`starting-setup-${id}-prologue`}><FieldLabelText field="startingSetups.*.prologue" /></Label>
          <MediaTagInsertButton name={`startingSetups.${index}.prologue`} fieldLabel="프롤로그" textareaRef={prologueRef} />
        </div>
        <Textarea
          id={`starting-setup-${id}-prologue`}
          placeholder="이 시작설정의 도입부를 입력해주세요"
          rows={3}
          aria-invalid={!!rowErrors?.prologue}
          aria-describedby={rowErrors?.prologue ? `starting-setup-${id}-prologue-error` : undefined}
          {...prologueField}
          ref={(element) => {
            prologueField.ref(element);
            prologueRef.current = element;
          }}
        />
        <UnknownMediaTagNotice name={`startingSetups.${index}.prologue`} />
        <StoryMacroNotice name={`startingSetups.${index}.prologue`} />
        {rowErrors?.prologue && (
          <p id={`starting-setup-${id}-prologue-error`} role="alert" className="text-xs text-destructive-text">
            {rowErrors.prologue.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={`starting-setup-${id}-opening-situation`}><FieldLabelText field="startingSetups.*.openingSituation" /></Label>
          <MediaTagInsertButton
            name={`startingSetups.${index}.openingSituation`}
            fieldLabel="시작상황"
            textareaRef={openingSituationRef}
          />
        </div>
        <Textarea
          id={`starting-setup-${id}-opening-situation`}
          placeholder="채팅 시작 시 상황을 입력해주세요"
          rows={2}
          aria-invalid={!!rowErrors?.openingSituation}
          aria-describedby={rowErrors?.openingSituation ? `starting-setup-${id}-opening-situation-error` : undefined}
          {...openingSituationField}
          ref={(element) => {
            openingSituationField.ref(element);
            openingSituationRef.current = element;
          }}
        />
        <UnknownMediaTagNotice name={`startingSetups.${index}.openingSituation`} />
        <StoryMacroNotice name={`startingSetups.${index}.openingSituation`} />
        <p className="text-xs text-muted-foreground">
          비워두면 채팅 시작 시 프롤로그가 첫 메시지로 노출돼요.
        </p>
        {rowErrors?.openingSituation && (
          <p
            id={`starting-setup-${id}-opening-situation-error`}
            role="alert"
            className="text-xs text-destructive-text"
          >
            {rowErrors.openingSituation.message}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor={`starting-setup-${id}-advanced-toggle`}><FieldLabelText field="startingSetups.*.$advanced" /></Label>
          <p className="text-sm text-muted-foreground">플레이가이드와 추천 답변을 추가할 수 있어요</p>
        </div>
        <Switch
          id={`starting-setup-${id}-advanced-toggle`}
          checked={isAdvancedOpen}
          onCheckedChange={setIsAdvancedOpen}
        />
      </div>

      {isAdvancedOpen && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`starting-setup-${id}-play-guide`}><FieldLabelText field="startingSetups.*.playGuide" /></Label>
            <Textarea
              id={`starting-setup-${id}-play-guide`}
              placeholder="사용자에게 노출할 플레이 안내를 입력해주세요"
              rows={3}
              aria-invalid={!!rowErrors?.playGuide}
              aria-describedby={rowErrors?.playGuide ? `starting-setup-${id}-play-guide-error` : undefined}
              {...register(`startingSetups.${index}.playGuide`)}
            />
            <MediaTagOutsideNotice name={`startingSetups.${index}.playGuide`} />
            <StoryMacroNotice name={`startingSetups.${index}.playGuide`} />
            {rowErrors?.playGuide && (
              <p id={`starting-setup-${id}-play-guide-error`} role="alert" className="text-xs text-destructive-text">
                {rowErrors.playGuide.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`starting-setup-${id}-reply-input`}>
              <FieldLabelText field="startingSetups.*.suggestedReplies" />
            </Label>
            {/* 상한에서도 입력칸과 [추가] 버튼을 트리에 남긴다.
                `disabled`도, 조건부 렌더도 안 된다(apps/web/CLAUDE.md §포커스) — 둘 다 4번째를 넣는
                순간 그 컨트롤이 blur/언마운트돼 포커스가 <body>로 떨어진다. 대신 `aria-disabled`로
                잠그고(ContentListLoadMore와 같은 레시피) 실제 차단은 handleAddSuggestedReply가 한다.
                같은 자리의 `설정 추가`는 useFieldArray.append()가 새 행으로 포커스를 옮겨 주므로
                조건부 렌더로 둔다 — 두 버튼에서 실제로 다른 값이다. */}
            <div className="flex gap-2">
              <Input
                id={`starting-setup-${id}-reply-input`}
                placeholder="추천 답변을 입력 후 추가해주세요"
                value={replyInput}
                onChange={(event) => setReplyInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") return;
                  event.preventDefault();
                  handleAddSuggestedReply();
                }}
              />
              <Button
                type="button"
                variant="secondary"
                aria-disabled={!canAddSuggestedReply}
                className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
                onClick={handleAddSuggestedReply}
              >
                추가
              </Button>
            </div>
            {suggestedReplies.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {suggestedReplies.map((reply) => (
                  <span
                    key={reply}
                    className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground"
                  >
                    {reply}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-4"
                      aria-label={`${reply} 추천 답변 삭제`}
                      onClick={() => handleRemoveSuggestedReply(reply)}
                    >
                      <X aria-hidden className="size-3" />
                    </Button>
                  </span>
                ))}
              </div>
            )}
            {/* 배열 자체의 위반(`.max`)은 인덱스가 아니라 이 키에 `.message`로 온다 — zodResolver를
                RHF가 부르는 모양대로 호출해 확인했다. */}
            {!!rowErrors?.suggestedReplies?.message && (
              <p
                id={`starting-setup-${id}-suggested-replies-error`}
                role="alert"
                className="text-xs text-destructive-text"
              >
                {rowErrors.suggestedReplies.message}
              </p>
            )}
          </div>
        </div>
      )}
    </CollapsibleItemCard>
  );
}
