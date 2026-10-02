import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useFormContext, useWatch } from "react-hook-form";

import { CollapsibleItemCard, ItemDragHandle, ItemRemoveButton, itemOpenKey } from "@/features/build-common";
import {
  excludeKeywordError,
  MAX_ALWAYS_ON_KEYWORD_NOTES,
  MAX_EXCLUDE_KEYWORDS,
  MAX_KEYWORD_NOTE_CONTENT_LENGTH,
  MAX_KEYWORD_NOTE_NAME_LENGTH,
  MAX_KEYWORD_NOTE_STICKY_TURNS,
  MAX_TRIGGER_KEYWORDS,
  triggerKeywordError,
  type StartingSetupValues,
  type StoryBuilderFormValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

import { KeywordChipField } from "./KeywordChipField";
import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";

const KEYWORD_NOTE_LIST: StoryCollapsibleList = "keywordNote";

const STICKY_TURN_OPTIONS = Array.from({ length: MAX_KEYWORD_NOTE_STICKY_TURNS + 1 }, (_, turns) => ({
  value: String(turns),
  label: turns === 0 ? "이번 턴만" : `다음 ${turns}턴까지`,
}));

type KeywordNoteCardProps = {
  id: string;
  index: number;
  startingSetups: StartingSetupValues[];
  /** 다른 노트들로 상시가 이미 꽉 찼는가 — 이 노트가 꺼져 있을 때만 스위치를 잠근다. */
  isAlwaysOnFull: boolean;
  onRemove: () => void;
  /** 화살표 키 재정렬 — 한 칸 위(-1)나 아래(1). */
  onStep: (step: -1 | 1) => void;
};

/**
 * 노트 한 장. 접기 머리 줄(핸들·순번·제목·상태 요약)과 접히는 본문(이름·정보·트리거 키워드·금지 키워드·유지 턴·상시·
 * 적용 대상). 칩·토글·선택은 노트 하위 경로에 `setValue` 한다 — 배열 통째로 바꾸면 카드가 다시 마운트돼 입력 중인 칸의
 * 포커스와 글자가 사라진다.
 *
 * 열림 키는 폼 값의 노트 id 다. `id` prop(필드 배열이 주는 id)은 탭을 다시 열 때마다 새로 발급돼 열림을 잃으므로 끌기·
 * DOM id 에만 쓴다.
 */
export function KeywordNoteCard({ id, index, startingSetups, isAlwaysOnFull, onRemove, onStep }: KeywordNoteCardProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    setValue,
    getValues,
    formState: { errors },
  } = form;
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id });
  const [noteId, name, content, triggerKeywords, excludeKeywords, stickyTurns, isAlwaysOn, scope] = useWatch({
    control,
    name: [
      `keywordNotes.${index}.id`,
      `keywordNotes.${index}.name`,
      `keywordNotes.${index}.content`,
      `keywordNotes.${index}.triggerKeywords`,
      `keywordNotes.${index}.excludeKeywords`,
      `keywordNotes.${index}.stickyTurns`,
      `keywordNotes.${index}.alwaysOn`,
      `keywordNotes.${index}.scope`,
    ],
  });
  const noteErrors = errors.keywordNotes?.[index];
  const isAlwaysOnLocked = !isAlwaysOn && isAlwaysOnFull;
  const position = index + 1;
  const title = name.trim() || triggerKeywords[0];
  const ids = {
    title: `keyword-note-${id}-title`,
    name: `keyword-note-${id}-name`,
    nameHint: `keyword-note-${id}-name-hint`,
    nameCount: `keyword-note-${id}-name-count`,
    content: `keyword-note-${id}-content`,
    contentCount: `keyword-note-${id}-content-count`,
    contentError: `keyword-note-${id}-content-error`,
    alwaysOnReason: `keyword-note-${id}-always-on-reason`,
    alwaysOnSwitch: `keyword-note-${id}-always-on`,
    alwaysOnHint: `keyword-note-${id}-always-on-hint`,
    alwaysOnLock: `keyword-note-${id}-always-on-lock`,
    sticky: `keyword-note-${id}-sticky`,
    scopeError: `keyword-note-${id}-scope-error`,
  };

  function setKeywords(field: "triggerKeywords" | "excludeKeywords", next: string[]) {
    setValue(`keywordNotes.${index}.${field}`, next, { shouldDirty: true });
  }

  function handleAlwaysOnChange(checked: boolean) {
    // 상시는 스토리당 최대 3개다. 자동저장은 발행 검사를 거치지 않아 4번째가 폼에 들어가면 서버가 저장을 거절하고
    // 그 초안의 자동저장 전체가 멈춘다 — 스위치의 잠금 표시는 포인터만 막으므로 키보드로 눌러도 여기서 막는다.
    // 렌더 때의 개수가 아니라 지금 폼 값으로 다시 센다.
    if (checked && getValues("keywordNotes").filter((note) => note.alwaysOn).length >= MAX_ALWAYS_ON_KEYWORD_NOTES) {
      return;
    }
    setValue(`keywordNotes.${index}.alwaysOn`, checked, { shouldDirty: true });
  }

  function handleScopeKindChange(value: string) {
    if (!value) return;
    if (value === "global") {
      setValue(`keywordNotes.${index}.scope`, { kind: "global" }, { shouldDirty: true });
      return;
    }
    const currentScope = getValues(`keywordNotes.${index}.scope`);
    const defaultSetupId = currentScope.kind === "startingSetup" ? currentScope.startingSetupId : startingSetups[0]?.id;
    if (!defaultSetupId) return;
    setValue(
      `keywordNotes.${index}.scope`,
      { kind: "startingSetup", startingSetupId: defaultSetupId },
      { shouldDirty: true },
    );
  }

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      aria-labelledby={ids.title}
    >
      <CollapsibleItemCard
        openKey={itemOpenKey(KEYWORD_NOTE_LIST, noteId)}
        title={title}
        placeholderTitle="새 노트"
        srTitlePrefix={`${position}번째 노트: `}
        titleId={ids.title}
        summary={
          <KeywordNoteSummary isAlwaysOn={isAlwaysOn} stickyTurns={stickyTurns} triggerCount={triggerKeywords.length} />
        }
        hasError={!!noteErrors}
        leading={
          <>
            {/* 화살표 키 재정렬은 손잡이에만 건다 — 토글에 걸면 머리 줄을 지나며 누른 화살표가 순서를 바꾼다. */}
            <ItemDragHandle
              id={keywordNoteHandleId(id)}
              {...attributes}
              {...listeners}
              aria-roledescription="순서 핸들"
              aria-label={`${position}번째 노트 순서 변경`}
              onKeyDown={(event) => {
                if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
                event.preventDefault();
                onStep(event.key === "ArrowUp" ? -1 : 1);
              }}
            />
            <span
              className="w-6 shrink-0 text-center text-sm font-semibold tabular-nums text-muted-foreground"
              aria-hidden
            >
              {position}
            </span>
          </>
        }
        trailing={<ItemRemoveButton label={`${position}번째 노트 삭제`} onClick={onRemove} />}
      >
        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <Label htmlFor={ids.name}>이름</Label>
            <span id={ids.nameCount} className="text-xs tabular-nums text-muted-foreground">
              <span className="sr-only">이름 </span>
              {name.length}/{MAX_KEYWORD_NOTE_NAME_LENGTH}
            </span>
          </div>
          {/* `maxLength` 는 UTF-16 단위로 세어 서버(코드 포인트)와 같거나 더 엄격하다 — 상한을 넘는 이름이 폼에 생기지
            않는다. 카운터도 같은 단위로 센다. */}
          <Input
            id={ids.name}
            placeholder="목록에서 알아볼 이름(선택)"
            maxLength={MAX_KEYWORD_NOTE_NAME_LENGTH}
            aria-describedby={`${ids.nameHint} ${ids.nameCount}`}
            aria-invalid={!!noteErrors?.name}
            {...register(`keywordNotes.${index}.name`)}
          />
          <p id={ids.nameHint} className="text-xs text-muted-foreground">
            목록에서만 보여요. AI에게는 보내지 않아요.
          </p>
          {!!noteErrors?.name && (
            <p role="alert" className="text-xs text-destructive-text">
              {noteErrors.name.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <Label htmlFor={ids.content}>정보 *</Label>
            <span id={ids.contentCount} className="text-xs tabular-nums text-muted-foreground">
              <span className="sr-only">정보 </span>
              {content.length}/{MAX_KEYWORD_NOTE_CONTENT_LENGTH}
            </span>
          </div>
          {/* 브라우저의 `maxLength` 는 UTF-16 단위로 세어 서버(코드 포인트)와 같거나 더 엄격하다 — 상한을 넘는 정보가
            폼에 생기지 않는다. 카운터도 같은 단위로 센다. */}
          <Textarea
            id={ids.content}
            placeholder="키워드가 나오면 AI가 참고할 정보를 적어 주세요. 대상의 이름도 함께 적어 주세요."
            rows={3}
            maxLength={MAX_KEYWORD_NOTE_CONTENT_LENGTH}
            aria-invalid={!!noteErrors?.content}
            aria-describedby={noteErrors?.content ? `${ids.contentCount} ${ids.contentError}` : ids.contentCount}
            {...register(`keywordNotes.${index}.content`)}
          />
          <MediaTagOutsideNotice name={`keywordNotes.${index}.content`} />
          {!!noteErrors?.content && (
            <p id={ids.contentError} role="alert" className="text-xs text-destructive-text">
              {noteErrors.content.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <KeywordChipField
            idPrefix={`keyword-note-${id}-trigger`}
            label="트리거 키워드"
            isRequired={!isAlwaysOn}
            chipNoun="트리거 키워드"
            placeholder="입력 후 Enter 또는 추가"
            keywords={triggerKeywords}
            limit={MAX_TRIGGER_KEYWORDS}
            limitReason={`트리거 키워드는 최대 ${MAX_TRIGGER_KEYWORDS}개예요. 더 넣으려면 하나를 지워 주세요.`}
            validate={(keyword) => triggerKeywordError(keyword, triggerKeywords)}
            onAdd={(keyword) => setKeywords("triggerKeywords", [...triggerKeywords, keyword])}
            onRemove={(keyword) =>
              setKeywords(
                "triggerKeywords",
                triggerKeywords.filter((item) => item !== keyword),
              )
            }
            chipStyle="filled"
            disabled={isAlwaysOn}
            disabledReasonId={ids.alwaysOnReason}
            error={noteErrors?.triggerKeywords?.message}
            fieldPath={`keywordNotes.${index}.triggerKeywords`}
          />
          {isAlwaysOn && (
            <p id={ids.alwaysOnReason} className="text-xs break-keep text-muted-foreground">
              상시 노트는 키워드 없이 매 턴 실려서 트리거 키워드와 유지 턴을 쓰지 않아요. 상시를 끄면 넣어 둔 키워드가
              다시 쓰여요.
            </p>
          )}
        </div>

        <KeywordChipField
          idPrefix={`keyword-note-${id}-exclude`}
          label="금지 키워드"
          chipNoun="금지 키워드"
          placeholder="이 단어가 나온 턴엔 노트를 빼요"
          keywords={excludeKeywords}
          limit={MAX_EXCLUDE_KEYWORDS}
          limitReason={`금지 키워드는 최대 ${MAX_EXCLUDE_KEYWORDS}개예요. 더 넣으려면 하나를 지워 주세요.`}
          validate={(keyword) => excludeKeywordError(keyword, excludeKeywords)}
          onAdd={(keyword) => setKeywords("excludeKeywords", [...excludeKeywords, keyword])}
          onRemove={(keyword) =>
            setKeywords(
              "excludeKeywords",
              excludeKeywords.filter((item) => item !== keyword),
            )
          }
          chipStyle="outlined"
          error={noteErrors?.excludeKeywords?.message}
          fieldPath={`keywordNotes.${index}.excludeKeywords`}
        />

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={ids.sticky}>유지 턴</Label>
          <Select
            value={String(stickyTurns)}
            disabled={isAlwaysOn}
            onValueChange={(value) =>
              setValue(`keywordNotes.${index}.stickyTurns`, Number(value), { shouldDirty: true })
            }
          >
            <SelectTrigger
              id={ids.sticky}
              className="w-40"
              aria-describedby={isAlwaysOn ? ids.alwaysOnReason : undefined}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STICKY_TURN_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs break-keep text-muted-foreground">키워드가 나온 뒤 몇 턴 더 노트를 실을지 정해요.</p>
        </div>

        <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
          <div className="flex flex-col gap-0.5">
            <Label htmlFor={ids.alwaysOnSwitch}>상시 적용</Label>
            <p id={ids.alwaysOnHint} className="text-sm break-keep text-muted-foreground">
              키워드 없이 매 턴 실어요. 금지 키워드가 나온 턴엔 빠져요.
            </p>
            {isAlwaysOnLocked && (
              <p id={ids.alwaysOnLock} className="text-xs break-keep text-muted-foreground">
                상시 노트는 최대 {MAX_ALWAYS_ON_KEYWORD_NOTES}개예요. 다른 노트의 상시를 끄면 켤 수 있어요.
              </p>
            )}
          </div>
          {/* 잠글 때 `disabled` 가 아니라 `aria-disabled` 다 — 사유가 키보드·스크린리더에도 닿아야 해서 포커스 순서에
            남긴다. 실제 차단은 handleAlwaysOnChange 다. */}
          <Switch
            id={ids.alwaysOnSwitch}
            checked={isAlwaysOn}
            onCheckedChange={handleAlwaysOnChange}
            aria-disabled={isAlwaysOnLocked}
            aria-describedby={isAlwaysOnLocked ? `${ids.alwaysOnHint} ${ids.alwaysOnLock}` : ids.alwaysOnHint}
            className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label>적용 대상 *</Label>
          <ToggleGroup
            type="single"
            variant="outline"
            value={scope.kind}
            onValueChange={handleScopeKindChange}
            aria-label="적용 대상"
            aria-invalid={!!noteErrors?.scope}
            aria-describedby={noteErrors?.scope ? ids.scopeError : undefined}
          >
            <ToggleGroupItem
              value="global"
              aria-label="스토리 전체"
              className={cn(noteErrors?.scope && "border-destructive ring-3 ring-destructive/20")}
            >
              스토리 전체
            </ToggleGroupItem>
            <ToggleGroupItem
              value="startingSetup"
              aria-label="특정 시작설정"
              disabled={startingSetups.length === 0}
              className={cn(noteErrors?.scope && "border-destructive ring-3 ring-destructive/20")}
            >
              특정 시작설정
            </ToggleGroupItem>
          </ToggleGroup>
          {!!noteErrors?.scope && (
            <p id={ids.scopeError} role="alert" className="text-xs text-destructive-text">
              {noteErrors.scope.message}
            </p>
          )}

          {scope.kind === "startingSetup" && (
            <ToggleGroup
              type="single"
              variant="outline"
              className="flex-wrap"
              value={scope.startingSetupId}
              onValueChange={(value) =>
                value &&
                setValue(
                  `keywordNotes.${index}.scope`,
                  { kind: "startingSetup", startingSetupId: value },
                  { shouldDirty: true },
                )
              }
              aria-label="적용할 시작설정 선택"
            >
              {startingSetups.map((setup, setupIndex) => (
                <ToggleGroupItem
                  key={setup.id}
                  value={setup.id}
                  aria-label={setup.name || `시작설정 ${setupIndex + 1}`}
                >
                  {setup.name || `시작설정 ${setupIndex + 1}`}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        </div>
      </CollapsibleItemCard>
    </li>
  );
}

type KeywordNoteSummaryProps = {
  isAlwaysOn: boolean;
  stickyTurns: number;
  triggerCount: number;
};

/** 접힌 머리 줄 요약 — 상시 여부나 유지 턴, 트리거 개수. 상시 노트는 트리거 키워드와 유지 턴을 쓰지 않아 `상시` 만 보인다. */
function KeywordNoteSummary({ isAlwaysOn, stickyTurns, triggerCount }: KeywordNoteSummaryProps) {
  if (isAlwaysOn) return <span className="font-medium text-foreground">상시</span>;
  return (
    <>
      {stickyTurns > 0 && `유지 ${stickyTurns}턴 · `}
      트리거 {triggerCount}개
    </>
  );
}

/** 재정렬·삭제 뒤 탭이 포커스를 되돌릴 드래그 핸들의 id. */
export function keywordNoteHandleId(noteId: string): string {
  return `keyword-note-${noteId}-handle`;
}
