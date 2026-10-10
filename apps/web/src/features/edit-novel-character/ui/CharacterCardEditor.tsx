import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Merge, Pencil, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { useForm, useWatch } from "react-hook-form";

import {
  novelKeys,
  useUpdateNovelCharacterMutation,
  type NovelAction,
  type NovelCharacterResponse,
  type NovelCharacterUpdateRequest,
  type NovelDetailResponse,
} from "@/entities/novel";
import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";
import { CharacterCount } from "@/shared/ui/CharacterCount";

import {
  addAlias,
  countCharacterChars,
  createCharacterMemoSchema,
  createCharacterNameSchema,
  toCharacterSaveError,
  type CharacterMemoFormValues,
  type CharacterNameFormValues,
} from "../model/characterForm";
import { MergeCharacterModal } from "./MergeCharacterModal";

type CharacterCardEditorProps = {
  novel: NovelDetailResponse;
  character: NovelCharacterResponse;
  /** 이 소설의 인물 전부(합칠 대상을 고른다). */
  characters: readonly NovelCharacterResponse[];
  /** 카드 이름(`h2`, `tabIndex=-1`). 호출부가 인물을 고를 때 포커스를 보낼 자리다. */
  headingRef?: RefObject<HTMLHeadingElement | null>;
  /** 나온 화 칩을 눌렀을 때 — 호출부가 그 화를 고른다. */
  onSelectEpisode: (chapterId: string) => void;
  /** 다른 인물로 합친 뒤 — 이 카드는 사라졌으니 호출부가 남은 카드를 고른다. */
  onMerged: (intoCharacterId: string) => void;
  /** 메모에 저장하지 않은 입력이 있는가가 바뀔 때마다(사라질 때는 `false`). */
  onDraftDirtyChange?: (isDirty: boolean) => void;
};

/**
 * 편집 패널의 인물 카드 — 이름, 별칭, 메모, 나온 화, 다른 인물과 합치기. 고치는 자리마다 바로 서버에 저장한다(이름·
 * 별칭은 누르는 순간, 메모는 저장 버튼). 인물 카드를 단독으로 지우는 길은 없다 — 메모가 다음 묶음 입력에 실리는
 * 카드를 실수로 잃지 않게, 합치기만 둔다.
 *
 * 이 컴포넌트는 인물 id 로 `key` 를 받아야 한다 — 메모 폼이 처음 받은 메모로 굳고(쓰는 도중 목록을 다시 받아도 입력을
 * 덮지 않는다), 다른 인물로 바뀌면 새로 굳어야 한다.
 */
export function CharacterCardEditor({
  novel,
  character,
  characters,
  headingRef,
  onSelectEpisode,
  onMerged,
  onDraftDirtyChange,
}: CharacterCardEditorProps) {
  const queryClient = useQueryClient();
  const mutation = useUpdateNovelCharacterMutation();
  const appearedChapters = novel.chapters
    .filter((chapter) => character.chapterIds.includes(chapter.id))
    .sort((a, b) => a.ordinal - b.ordinal);
  const mergeCandidates = characters.filter((candidate) => candidate.id !== character.id);
  const mergeReasonId = useId();

  /** 보낸 칸만 바꾼다. 실패 문장을 돌려주고(성공이면 `undefined`), 카드가 사라졌으면 목록을 다시 받는다. */
  async function update(body: NovelCharacterUpdateRequest, action: NovelAction): Promise<string | undefined> {
    try {
      await mutation.mutateAsync({ novelId: novel.id, characterId: character.id, body });
      return undefined;
    } catch (error) {
      const notice = toCharacterSaveError(error, action);
      // 재동의가 필요하면 전역 재동의 모달이 맡는다. 입력은 그대로 남아 동의 뒤 다시 저장할 수 있다.
      if (notice === null) return "";
      if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.characters(novel.id) });
      return notice.message;
    }
  }

  async function merge() {
    if (mergeCandidates.length === 0) return;
    const intoId = await MergeCharacterModal.call({
      novelId: novel.id,
      character: { id: character.id, name: character.name },
      candidates: mergeCandidates.map(({ id, name }) => ({ id, name })),
    });
    if (intoId !== null) onMerged(intoId);
  }

  return (
    <div className="flex flex-col gap-6">
      <CharacterNameField
        name={character.name}
        maxLength={novel.limits.characterNameMaxLength}
        headingRef={headingRef}
        onSave={(name) => update({ name }, "character")}
      />
      <CharacterAliasesField
        name={character.name}
        aliases={character.aliases}
        maxCount={novel.limits.characterAliasesMaxCount}
        maxLength={novel.limits.characterNameMaxLength}
        isSaving={mutation.isPending}
        onSave={(aliases) => update({ aliases }, "character")}
      />
      <CharacterMemoField
        memo={character.memo}
        maxLength={novel.limits.characterMemoMaxLength}
        onSave={(memo) => update({ memo }, "character")}
        onDraftDirtyChange={onDraftDirtyChange}
      />

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-foreground">나온 화</h3>
        {appearedChapters.length === 0 ? (
          <p className="text-sm break-keep text-muted-foreground">지금 있는 화에는 나오지 않아요.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {appearedChapters.map((chapter) => (
              <li key={chapter.id}>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="rounded-full tabular-nums"
                  onClick={() => onSelectEpisode(chapter.id)}
                >
                  {chapter.ordinal}화
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="flex flex-col items-start gap-2 border-t border-border pt-6">
        <Button
          type="button"
          variant="outline"
          aria-disabled={mergeCandidates.length === 0}
          aria-describedby={mergeCandidates.length === 0 ? mergeReasonId : undefined}
          className="aria-disabled:opacity-65"
          onClick={() => void merge()}
        >
          <Merge aria-hidden />
          다른 인물과 합치기
        </Button>
        {mergeCandidates.length === 0 && (
          <p id={mergeReasonId} className="text-sm break-keep text-muted-foreground">
            합칠 다른 인물이 없어요.
          </p>
        )}
      </div>
    </div>
  );
}

type CharacterNameFieldProps = {
  name: string;
  maxLength: number;
  headingRef: RefObject<HTMLHeadingElement | null> | undefined;
  /** 저장하고 실패 문장을 돌려준다(성공이면 `undefined`, 다른 곳이 알린 실패면 빈 문자열). */
  onSave: (name: string) => Promise<string | undefined>;
};

/** 카드 이름(`h2`)과 그 자리 고치기. 다른 카드가 쓰는 이름이면 서버가 겹친 이름을 알려 와 그 이름으로 말한다. */
function CharacterNameField({ name, maxLength, headingRef, onSave }: CharacterNameFieldProps) {
  const inputId = useId();
  const errorId = useId();
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | undefined>(undefined);
  const pencilRef = useRef<HTMLButtonElement>(null);
  const shouldFocusPencilRef = useRef(false);
  const form = useForm<CharacterNameFormValues>({
    resolver: zodResolver(createCharacterNameSchema(maxLength)),
    defaultValues: { name },
  });
  const errorMessage = form.formState.errors.name?.message ?? saveError;

  useEffect(() => {
    if (isEditing || !shouldFocusPencilRef.current) return;
    shouldFocusPencilRef.current = false;
    pencilRef.current?.focus();
  }, [isEditing]);

  function finishEditing() {
    shouldFocusPencilRef.current = true;
    setIsEditing(false);
  }

  async function handleValidSubmit(values: CharacterNameFormValues) {
    setIsSaving(true);
    setSaveError(undefined);
    const failure = await onSave(values.name.trim());
    setIsSaving(false);
    if (failure === undefined) finishEditing();
    else if (failure !== "") setSaveError(failure);
  }

  if (isEditing) {
    return (
      <form
        noValidate
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (isSaving) return;
          void form.handleSubmit(handleValidSubmit)(event);
        }}
      >
        <h2 ref={headingRef} tabIndex={-1} className="sr-only">
          {name}
        </h2>
        <label htmlFor={inputId} className="text-sm font-medium text-foreground">
          인물 이름
        </label>
        <Input
          id={inputId}
          autoFocus
          autoComplete="off"
          aria-invalid={errorMessage !== undefined}
          aria-describedby={errorMessage !== undefined ? errorId : undefined}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            finishEditing();
          }}
          {...form.register("name")}
        />
        {errorMessage !== undefined && (
          <p id={errorId} role="alert" className="text-sm break-keep text-destructive-text">
            {errorMessage}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="secondary" size="sm" aria-disabled={isSaving} className="aria-disabled:opacity-65">
            {isSaving ? "저장 중…" : "저장"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={finishEditing}>
            취소
          </Button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex items-start gap-1">
      <h2 ref={headingRef} tabIndex={-1} className="min-w-0 text-xl font-semibold break-keep text-foreground outline-none">
        {name}
      </h2>
      <Button
        ref={pencilRef}
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="인물 이름 고치기"
        className="shrink-0"
        onClick={() => {
          form.reset({ name });
          setSaveError(undefined);
          setIsEditing(true);
        }}
      >
        <Pencil aria-hidden />
      </Button>
    </div>
  );
}

type CharacterAliasesFieldProps = {
  name: string;
  aliases: string[];
  maxCount: number;
  maxLength: number;
  isSaving: boolean;
  onSave: (aliases: string[]) => Promise<string | undefined>;
};

/**
 * 별칭 칩 목록과 더하기 입력. 더하거나 지우는 즉시 목록 전체를 저장한다(서버는 보낸 목록으로 통째로 바꾼다). 생성
 * 출력이 이 별칭으로 인물을 부르면 이 카드에 붙는다는 것을 설명 한 줄로 말한다.
 *
 * 칩의 지우기 버튼은 칩과 함께 사라지므로 누르기 전에 포커스를 더하기 입력으로 옮긴다.
 */
function CharacterAliasesField({ name, aliases, maxCount, maxLength, isSaving, onSave }: CharacterAliasesFieldProps) {
  const headingId = useId();
  const descriptionId = useId();
  const errorId = useId();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  async function save(next: string[]) {
    setError(undefined);
    const failure = await onSave(next);
    if (failure === undefined) return true;
    if (failure !== "") setError(failure);
    return false;
  }

  async function handleAdd() {
    if (isSaving) return;
    if (countCharacterChars(draft) > maxLength) {
      setError(`이름은 ${maxLength.toLocaleString()}자까지 쓸 수 있어요`);
      return;
    }
    const result = addAlias(aliases, name, draft, maxCount);
    if ("error" in result) {
      setError(result.error);
      return;
    }
    if (await save(result.aliases)) setDraft("");
  }

  function handleRemove(alias: string) {
    if (isSaving) return;
    inputRef.current?.focus();
    void save(aliases.filter((item) => item !== alias));
  }

  return (
    <section aria-labelledby={headingId} aria-describedby={descriptionId} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 id={headingId} className="text-sm font-semibold text-foreground">
          별칭
        </h3>
        <span className="text-xs text-muted-foreground tabular-nums">
          {aliases.length}/{maxCount}
        </span>
      </div>
      <p id={descriptionId} className="text-xs break-keep text-muted-foreground">
        AI가 이 인물을 다른 이름으로 부르면 그 이름을 여기 더해 주세요. 다음 화부터 이 카드로 모여요.
      </p>
      {aliases.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {aliases.map((alias) => (
            <li key={alias} className="inline-flex h-8 items-center gap-1 rounded-full border border-border pr-1 pl-3 text-sm">
              <span className="break-keep">{alias}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`‘${alias}’ 별칭 지우기`}
                aria-disabled={isSaving}
                className="rounded-full aria-disabled:opacity-65"
                onClick={() => handleRemove(alias)}
              >
                <X aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        noValidate
        className="flex items-start gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void handleAdd();
        }}
      >
        <Input
          ref={inputRef}
          value={draft}
          autoComplete="off"
          aria-label="더할 별칭"
          aria-invalid={error !== undefined}
          aria-describedby={error !== undefined ? errorId : undefined}
          placeholder="예: 도희 씨"
          onChange={(event) => {
            setDraft(event.target.value);
            setError(undefined);
          }}
        />
        <Button type="submit" variant="outline" aria-disabled={isSaving} className="shrink-0 aria-disabled:opacity-65">
          <Plus aria-hidden />
          더하기
        </Button>
      </form>
      {error !== undefined && (
        <p id={errorId} role="alert" className="text-sm break-keep text-destructive-text">
          {error}
        </p>
      )}
    </section>
  );
}

type CharacterMemoFieldProps = {
  memo: string;
  maxLength: number;
  onSave: (memo: string) => Promise<string | undefined>;
  onDraftDirtyChange?: (isDirty: boolean) => void;
};

/** 인물 메모. 다음 화를 만들 때 AI 에게 함께 보내므로 그 사실을 머리 아래에 적는다. 저장 버튼으로만 저장한다 — 쓰는
 * 도중의 값이 생성 입력에 실리면 안 된다. 기준값은 처음 한 번 굳히고 저장하면 저장한 값으로 다시 굳힌다. */
function CharacterMemoField({ memo, maxLength, onSave, onDraftDirtyChange }: CharacterMemoFieldProps) {
  const headingId = useId();
  const descriptionId = useId();
  const countId = useId();
  const errorId = useId();
  const [isSaving, setIsSaving] = useState(false);
  const [result, setResult] = useState<{ tone: "error" | "done"; message: string } | undefined>(undefined);
  const form = useForm<CharacterMemoFormValues>({
    resolver: zodResolver(createCharacterMemoSchema(maxLength)),
    defaultValues: { memo },
  });
  const value = useWatch({ control: form.control, name: "memo" });
  const fieldError = form.formState.errors.memo?.message;
  const { isDirty } = form.formState;
  // 저장하지 않은 입력이 있는가를 호출부에 알린다 — 호출부가 다른 것을 고르거나 뒤로 가기 전에 버릴지 묻는다.
  // 사라질 때는 거짓으로 돌려놓는다. 호출부 함수는 렌더마다 새로 만들어질 수 있어 ref 로 읽는다.
  const onDraftDirtyChangeRef = useRef(onDraftDirtyChange);
  onDraftDirtyChangeRef.current = onDraftDirtyChange;
  useEffect(() => {
    onDraftDirtyChangeRef.current?.(isDirty);
  }, [isDirty]);
  useEffect(() => () => onDraftDirtyChangeRef.current?.(false), []);

  async function handleValidSubmit(values: CharacterMemoFormValues) {
    const trimmed = values.memo.trim();
    setIsSaving(true);
    setResult(undefined);
    const failure = await onSave(trimmed);
    setIsSaving(false);
    if (failure === undefined) {
      form.reset({ memo: trimmed });
      setResult({ tone: "done", message: "메모를 저장했어요. 다음 화부터 반영돼요." });
    } else if (failure !== "") {
      setResult({ tone: "error", message: failure });
    }
  }

  let status: string | null = null;
  if (isDirty) status = "저장하지 않은 변경이 있어요.";
  else if (result?.tone === "done") status = result.message;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="text-sm font-semibold text-foreground">
        메모
      </h3>
      <p id={descriptionId} className="text-xs break-keep text-muted-foreground">
        다음 화를 만들 때 AI에게 함께 보내요. 비워 두면 보내지 않아요.
      </p>
      <form
        noValidate
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (isSaving) return;
          void form.handleSubmit(handleValidSubmit)(event);
        }}
      >
        <BuilderTextarea
          aria-labelledby={headingId}
          aria-invalid={fieldError !== undefined}
          aria-describedby={[descriptionId, countId, fieldError !== undefined && errorId].filter(Boolean).join(" ")}
          rows={5}
          placeholder="예: 편의점 야간 점원. 손님에게는 존댓말, 동생에게는 반말."
          {...form.register("memo")}
        />
        <CharacterCount id={countId} count={countCharacterChars(value)} max={maxLength} />
        {fieldError !== undefined && (
          <p id={errorId} role="alert" className="text-sm break-keep text-destructive-text">
            {fieldError}
          </p>
        )}
        {result?.tone === "error" && (
          <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
            {result.message}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="secondary" size="sm" aria-disabled={isSaving} className="aria-disabled:opacity-65">
            {isSaving ? "저장 중…" : "메모 저장"}
          </Button>
          {/* 저장 결과와 저장하지 않은 변경을 알리는 줄. 항상 마운트해 바뀌는 순간을 화면 낭독기가 놓치지 않는다. */}
          <p aria-live="polite" className="text-sm break-keep text-muted-foreground empty:sr-only">
            {status}
          </p>
        </div>
      </form>
    </section>
  );
}
