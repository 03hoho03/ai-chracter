import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";

import { novelKeys, toNovelActionError, type NovelDetailResponse } from "@/entities/novel";

import { useSaveNovelNotesMutation } from "../api/useSaveNovelNotesMutation";
import { formToServer } from "../model/formToServer";
import { countNotesChars, notesFormOptions, type NotesFormValues } from "../model/schema";
import { serverToForm } from "../model/serverToForm";

type NovelNotesEditorProps = {
  novel: NovelDetailResponse;
  /** 노트 제목(`h2`, `tabIndex=-1`). 호출부가 노트를 열 때 포커스를 보낼 자리다. */
  headingRef?: RefObject<HTMLHeadingElement | null>;
  /** 저장하지 않은 입력이 있는가가 바뀔 때마다(사라질 때는 `false`). */
  onDraftDirtyChange?: (isDirty: boolean) => void;
};

/** 설정 노트 — 소설 내내 지켜야 할 짧은 사실을 한 줄씩. 다음 화를 만들 때와 AI로 고칠 때 함께 전해진다.
 *
 * 저장 버튼으로만 저장한다(입력마다 저장하지 않는다 — 노트는 다음 작업을 부를 때만 쓰여 고치는 도중 값이 서버에
 * 있을 이유가 없다). 기준값은 처음 한 번 굳히고, 저장하면 응답으로 다시 굳힌다 — 쓰는 도중 상세를 다시 받아도
 * 입력을 덮지 않는다. 다른 소설로 옮기면 호출부가 `key` 로 새로 마운트한다.
 *
 * 저장 결과 문장과 실패 문장은 누른 순간 기록한 상태다. 저장 중에는 `aria-disabled` 로 막아 포커스를 지킨다. */
export function NovelNotesEditor({ novel, headingRef, onDraftDirtyChange }: NovelNotesEditorProps) {
  const queryClient = useQueryClient();
  const headingId = useId();
  const descriptionId = useId();
  const countId = useId();
  const errorId = useId();
  const maxLength = novel.limits.settingNotesMaxLength;
  const form = useForm<NotesFormValues>({
    ...notesFormOptions(maxLength),
    defaultValues: serverToForm(novel.settingNotes),
  });
  const { fields, append, remove } = useFieldArray({ control: form.control, name: "notes" });
  const notes = useWatch({ control: form.control, name: "notes" });
  const length = countNotesChars(formToServer({ notes }).settingNotes);
  const saveMutation = useSaveNovelNotesMutation();
  const [result, setResult] = useState<{ tone: "error" | "done"; message: string } | undefined>(undefined);
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const { errors, isDirty } = form.formState;
  // 배열 칸 오류는 폼이 그 배열을 어떻게 등록했느냐에 따라 배열 자리나 그 `root` 자리 둘 중 하나에 담긴다.
  const lengthError = errors.notes?.root?.message ?? errors.notes?.message;
  const isSaving = saveMutation.isPending;
  // 저장하지 않은 입력이 있는가를 호출부에 알린다 — 호출부가 다른 것을 고르거나 뒤로 가기 전에 버릴지 묻는다.
  // 사라질 때는 거짓으로 돌려놓는다. 호출부 함수는 렌더마다 새로 만들어질 수 있어 ref 로 읽는다.
  const onDraftDirtyChangeRef = useRef(onDraftDirtyChange);
  onDraftDirtyChangeRef.current = onDraftDirtyChange;
  useEffect(() => {
    onDraftDirtyChangeRef.current?.(isDirty);
  }, [isDirty]);
  useEffect(() => () => onDraftDirtyChangeRef.current?.(false), []);

  async function handleValidSubmit(values: NotesFormValues) {
    setResult(undefined);
    try {
      const saved = await saveMutation.mutateAsync({ novelId: novel.id, ...formToServer(values) });
      form.reset(serverToForm(saved.settingNotes));
      setResult({ tone: "done", message: "설정 노트를 저장했어요. 다음 화와 AI 수정부터 반영돼요." });
    } catch (error) {
      const notice = toNovelActionError(error, "notes");
      // 재동의가 필요하면 전역 재동의 모달이 맡는다. 쓴 글은 그대로 남아 동의 뒤 다시 저장할 수 있다.
      if (notice === null) return;
      setResult({ tone: "error", message: notice.message });
      // 소설이 지워졌거나 허용이 회수된 실패는 상세를 다시 받아야 화면이 「찾을 수 없어요」·잠김 화면으로 넘어간다.
      if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }

  function removeNote(index: number) {
    // 지우기 버튼이 줄과 함께 사라지며 포커스가 `<body>` 로 떨어지지 않게, 남는 칸으로 먼저 옮긴다(다음 줄, 없으면
    // 앞 줄, 둘 다 없으면 더하기 버튼). 남는 줄은 key 가 그대로라 다시 그려지지 않는다.
    const next = fields[index + 1] ?? fields[index - 1];
    if (next === undefined) addButtonRef.current?.focus();
    else form.setFocus(`notes.${fields.indexOf(next)}.text`);
    remove(index);
  }

  return (
    <section aria-labelledby={headingId} aria-describedby={descriptionId} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        {/* 조작 대상이 아니라 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
        <h2 ref={headingRef} id={headingId} tabIndex={-1} className="text-lg font-semibold text-foreground outline-none">
          설정 노트
        </h2>
        <p id={descriptionId} className="text-sm break-keep text-muted-foreground">
          이름·관계·말버릇처럼 소설 내내 지켜야 할 사실을 한 줄에 하나씩 적어주세요. 다음 화를 만들 때와 AI로 고칠 때
          함께 전해요.
        </p>
      </div>

      <form
        noValidate
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (isSaving) return;
          void form.handleSubmit(handleValidSubmit)(event);
        }}
      >
        {fields.length === 0 ? (
          <p className="text-sm break-keep text-muted-foreground">아직 적은 설정이 없어요.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {fields.map((field, index) => (
              <li key={field.id} className="flex items-center gap-2">
                <Input
                  aria-label={`${index + 1}번째 설정`}
                  aria-invalid={lengthError !== undefined}
                  aria-describedby={lengthError !== undefined ? `${countId} ${errorId}` : countId}
                  autoComplete="off"
                  placeholder="예: 서윤은 주인공을 선배라고 부른다"
                  {...form.register(`notes.${index}.text`)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`${index + 1}번째 설정 지우기`}
                  className="shrink-0"
                  onClick={() => removeNote(index)}
                >
                  <Trash2 aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button
            ref={addButtonRef}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => append({ id: crypto.randomUUID(), text: "" })}
          >
            <Plus aria-hidden />
            설정 더하기
          </Button>
          <p id={countId} className="text-xs text-muted-foreground tabular-nums">
            {length.toLocaleString()} / {maxLength.toLocaleString()}자
          </p>
        </div>

        {lengthError !== undefined && (
          <p id={errorId} role="alert" className="text-sm break-keep text-destructive-text">
            {lengthError}
          </p>
        )}
        {result?.tone === "error" && (
          <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
            {result.message}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="secondary" aria-disabled={isSaving} className="aria-disabled:opacity-65">
            {isSaving ? "저장 중…" : "설정 노트 저장"}
          </Button>
          {/* 저장 결과와 저장하지 않은 변경을 알리는 줄. 항상 마운트해 바뀌는 순간을 화면 낭독기가 놓치지 않는다. */}
          <p aria-live="polite" className="text-sm break-keep text-muted-foreground empty:sr-only">
            {toSaveStatus(isDirty, result)}
          </p>
        </div>
      </form>
    </section>
  );
}

/** 저장 버튼 옆 한 줄. 저장하지 않은 변경이 먼저다(방금 저장했어도 그 뒤에 또 고쳤으면 그쪽이 지금 사실이다). */
function toSaveStatus(isDirty: boolean, result: { tone: "error" | "done"; message: string } | undefined): string | null {
  if (isDirty) return "저장하지 않은 변경이 있어요.";
  if (result?.tone === "done") return result.message;
  return null;
}
