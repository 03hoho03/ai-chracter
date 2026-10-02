import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useFormContext } from "react-hook-form";
import { toast } from "sonner";

import { normalizeMediaBookName, type MediaBookAxis } from "@/entities/media-book";
import { CollapsibleSection, itemOpenKey, useBuilderUiState } from "@/features/build-common";
import {
  MEDIA_BOOK_AXIS_SECTION_LIST,
  addAxisItem,
  axisItems,
  countAxisItemCells,
  mediaBookNameError,
  removeAxisItem,
  renameAxisItem,
  renameMediaTagsInFields,
  type MediaBookAxisValues,
  type StoryBuilderFormValues,
} from "@/features/build-story";
import { MediaBookConfirmModal } from "@/features/edit-media-book";

import { useMediaBookEditor } from "../model/useMediaBookEditor";

type MediaBookAxisListProps = { axis: MediaBookAxis };

const AXIS_LABEL = { person: "인물", scene: "장면" } as const satisfies Record<MediaBookAxis, string>;

/**
 * 인물 또는 장면 목록. 이름은 입력칸에서 바로 고치고(Enter·포커스 이동 때 반영, Esc 로 되돌림), 규칙에 맞지 않는
 * 이름은 폼에 쓰지 않고 입력칸 아래에 이유를 보인다 — 폼에는 언제나 서버가 받는 이름만 들어간다.
 *
 * 목록은 통째로 접힌다(머리 줄 `인물 3` + 이름 나열). 항목이 있으면 처음엔 접혀 있어 칸 상세가 한꺼번에 넣기 바로
 * 아래로 올라온다. 목록이 비었거나 저장하지 못한 이름이 남아 있으면 접지 못하게 펼쳐 둔다 — 비었으면 새 이름 입력칸이
 * 곧 첫 길이고, 저장하지 못한 이름은 그 이유가 입력칸 아래에만 있어 접으면 고쳤다고 믿게 된다(머리 줄은 폼에 남은 옛
 * 이름을 보인다). 접고 펴는 것은 화면 상태만 바꾸고 폼에는 아무것도 쓰지 않는다.
 */
export function MediaBookAxisList({ axis }: MediaBookAxisListProps) {
  const { getValues, setValue } = useFormContext<StoryBuilderFormValues>();
  const { mediaBook, getMediaBook, commit } = useMediaBookEditor();
  const items = axisItems(mediaBook, axis);
  const label = AXIS_LABEL[axis];
  const [newName, setNewName] = useState("");
  const [newNameError, setNewNameError] = useState<string>();
  // 줄마다 저장하지 못한 이름의 이유. 섹션이 접히지 않게 하려고 줄이 아니라 여기서 쥔다. 지운 줄의 이유가 남아도
  // 지금 목록에 있는 줄만 본다.
  const [rowErrors, setRowErrors] = useState<Readonly<Record<string, string>>>({});
  const hasUnsavedName = items.some((item) => rowErrors[item.id] !== undefined);
  const uiState = useBuilderUiState();
  const openKey = itemOpenKey(MEDIA_BOOK_AXIS_SECTION_LIST, axis);
  const listId = `media-book-${axis}`;

  function setRowError(id: string, error: string | undefined) {
    setRowErrors((prev) => {
      if (prev[id] === error) return prev;
      const next = { ...prev };
      if (error === undefined) delete next[id];
      else next[id] = error;
      return next;
    });
  }

  function handleAdd() {
    const current = getMediaBook();
    const error = mediaBookNameError(newName, axisItems(current, axis));
    if (error !== undefined) {
      setNewNameError(error);
      return;
    }
    // 비어 있던 목록은 열림 기록과 무관하게 펼쳐 둔 상태라 기록이 없을 수 있다. 첫 항목이 생기는 순간 기본
    // 접힘으로 바뀌어 방금 쓰던 입력칸이 숨지 않도록, 반영과 같은 핸들러에서 열림을 기록한다.
    uiState.open([openKey]);
    commit(addAxisItem(current, axis, newName, crypto.randomUUID()));
    setNewName("");
    setNewNameError(undefined);
  }

  /** 이름을 바꾸고, 태그가 그림이 되는 글 속 옛 이름 태그도 함께 바꾼다. 반영하지 못하면 이유를 돌려준다. */
  function handleRename(item: MediaBookAxisValues, name: string): string | undefined {
    const current = getMediaBook();
    const error = mediaBookNameError(name, axisItems(current, axis), item.id);
    if (error !== undefined) return error;
    commit(renameAxisItem(current, axis, item.id, name));
    const changes = renameMediaTagsInFields(getValues(), axis, item.name, name);
    for (const change of changes) setValue(change.path, change.value, { shouldDirty: true });
    if (changes.length > 0) toast(`글 속 이미지 표기 ${changes.length}곳도 새 이름으로 바꿨어요.`);
    return undefined;
  }

  async function handleRemove(item: MediaBookAxisValues) {
    const cellCount = countAxisItemCells(getMediaBook(), axis, item.id);
    if (cellCount > 0) {
      const trigger = document.activeElement;
      const isConfirmed = await MediaBookConfirmModal.call({
        title: `'${item.name}'${objectParticle(item.name)} 지울까요?`,
        description: `이 ${label}의 이미지 ${cellCount}장도 함께 지워져요. 글 속 표기는 그대로 남고 화면에는 빈칸이 돼요.`,
        confirmLabel: "지우기",
        // 취소면 지우기 버튼으로, 지웠으면 그 줄이 사라지므로 같은 목록의 새 이름 입력칸으로.
        onRestoreFocus: () => {
          if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
          else focusNewNameInput();
        },
      });
      if (!isConfirmed) return;
      commit(removeAxisItem(getMediaBook(), axis, item.id));
      return;
    }
    commit(removeAxisItem(getMediaBook(), axis, item.id));
    // 확인 없이 지운 경우도 누른 버튼이 줄째 사라진다 — 모달이 없으니 바로 옮긴다.
    focusNewNameInput();
  }

  function focusNewNameInput() {
    document.getElementById(`${listId}-new`)?.focus();
  }

  function handleNewNameKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    event.preventDefault();
    handleAdd();
  }

  return (
    // 제목은 목록의 이름이다 — 새 이름 입력칸의 이름은 입력칸에 따로 준다(이 글자를 이름으로 물려받으면 "인물 2"로
    // 읽힌다). 0 은 "아직 없음"을 숫자로 말할 뿐이라 덧붙이지 않는다.
    <CollapsibleSection
      openKey={openKey}
      title={items.length > 0 ? `${label} ${items.length}` : label}
      summary={items.map((item) => item.name).join(" · ")}
      isAlwaysOpen={items.length === 0 || hasUnsavedName}
      className="min-w-0"
    >
      {items.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label={`${label} 목록`}>
          {items.map((item) => (
            <AxisItemRow
              key={item.id}
              item={item}
              label={label}
              error={rowErrors[item.id]}
              onErrorChange={(error) => setRowError(item.id, error)}
              onRename={(name) => handleRename(item, name)}
              onRemove={() => void handleRemove(item)}
            />
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <Input
          id={`${listId}-new`}
          placeholder={`새 ${label} 이름`}
          aria-label={`새 ${label} 이름`}
          value={newName}
          aria-invalid={newNameError !== undefined}
          aria-describedby={newNameError !== undefined ? `${listId}-new-error` : undefined}
          onChange={(event) => {
            setNewName(event.target.value);
            setNewNameError(undefined);
          }}
          onKeyDown={handleNewNameKeyDown}
        />
        <Button type="button" variant="secondary" onClick={handleAdd}>
          추가
        </Button>
      </div>
      {newNameError !== undefined && (
        <p id={`${listId}-new-error`} role="alert" className="text-xs text-destructive-text">
          {newNameError}
        </p>
      )}
    </CollapsibleSection>
  );
}

type AxisItemRowProps = {
  item: MediaBookAxisValues;
  label: string;
  /** 저장하지 못한 이름의 이유. 목록이 쥔다(있으면 섹션이 접히지 않는다). */
  error: string | undefined;
  onErrorChange: (error: string | undefined) => void;
  /** 반영하지 못하면 이유를 돌려준다. */
  onRename: (name: string) => string | undefined;
  onRemove: () => void;
};

function AxisItemRow({ item, label, error, onErrorChange, onRename, onRemove }: AxisItemRowProps) {
  // 입력 중인 이름. 폼 값(item.name)은 반영할 때만 바뀐다.
  const [draftName, setDraftName] = useState(item.name);
  const inputId = `media-book-axis-${item.id}`;
  // 반영하지 못한 이름을 둔 채 이 줄이 사라지면(다른 탭으로 옮김) 입력이 말없이 옛 이름으로 돌아간다 — 그 사실을
  // 알린다. 정리 함수가 마지막 값을 읽도록 ref 에 둔다.
  const unsavedRef = useRef<string>(undefined);
  unsavedRef.current = error !== undefined ? `고친 ${label} 이름이 저장되지 않아 '${item.name}' 그대로예요.` : undefined;
  useEffect(
    () => () => {
      if (unsavedRef.current !== undefined) toast(unsavedRef.current);
    },
    [],
  );

  function commitDraft() {
    if (draftName === item.name) {
      onErrorChange(undefined);
      return;
    }
    const renameError = onRename(draftName);
    onErrorChange(renameError);
    // 폼에는 앞뒤 공백을 지운 이름이 들어가므로 입력칸도 그 값으로 맞춘다.
    if (renameError === undefined) setDraftName(normalizeMediaBookName(draftName));
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      commitDraft();
    } else if (event.key === "Escape") {
      setDraftName(item.name);
      onErrorChange(undefined);
    }
  }

  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <Input
          id={inputId}
          aria-label={`${label} 이름`}
          value={draftName}
          aria-invalid={error !== undefined}
          aria-describedby={error !== undefined ? `${inputId}-error` : undefined}
          onChange={(event) => setDraftName(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={handleKeyDown}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`${item.name} ${label} 지우기`}
          onClick={() => {
            // 지우는 줄이라 "옛 이름 그대로" 안내는 맞지 않다.
            onErrorChange(undefined);
            unsavedRef.current = undefined;
            onRemove();
          }}
        >
          <Trash2 aria-hidden />
        </Button>
      </div>
      {error !== undefined && (
        <p id={`${inputId}-error`} role="alert" className="text-xs text-destructive-text">
          {error} — 저장되지 않았어요(Esc 로 되돌리기).
        </p>
      )}
    </li>
  );
}

/** 목적격 조사 — 이름 끝 글자에 받침이 있으면 "을", 없으면 "를". 한글이 아닌 글자로 끝나면 둘 다 적는다. */
function objectParticle(word: string): string {
  const last = word.codePointAt(word.length - 1);
  const isHangulSyllable = last !== undefined && last >= 0xac00 && last <= 0xd7a3;
  if (!isHangulSyllable) return "을(를)";
  return (last - 0xac00) % 28 === 0 ? "를" : "을";
}
