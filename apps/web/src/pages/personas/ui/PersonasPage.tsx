import { useId, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Plus } from "lucide-react";

import { PersonaSummary, usePersonasQuery, type PersonaList } from "@/entities/persona";
import { CreatePersonaForm, EditPersonaForm, PersonaActionMenu } from "@/features/manage-persona";

/** 편집 대상은 화면에 하나뿐이다 — 생성 폼과 행 편집이 동시에 열리지 않게 단일 state로 쥔다
 * (apps/web/CLAUDE.md "인라인 편집 우선 — 편집 대상 id는 호출부 단일 state"). */
type EditingTarget = { kind: "create" } | { kind: "edit"; personaId: string } | undefined;

/** persona-goal-prompt.md UP-12 — 대화 프로필 관리(목록·생성·편집·삭제·기본 지정). 헤더 프로필 메뉴에서 들어온다.
 *
 * 컬럼은 설정(`/mypage`)과 같은 `max-w-md`다(§3-6 "폭은 마이페이지와 같게"). 편집은 모달이 아니라 행을
 * 폼으로 바꾸는 인라인 편집이다. */
export function PersonasPage() {
  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-8 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">대화 프로필</h1>
        <p className="text-sm break-keep text-muted-foreground">
          캐릭터에게 알려 줄 &lsquo;나&rsquo;예요. 대화방마다 하나를 고를 수 있고, 새 대화방은 기본 프로필로
          시작해요.
        </p>
      </div>

      <PersonasContent />
    </main>
  );
}

function PersonasContent() {
  const personasQuery = usePersonasQuery();
  const [editing, setEditing] = useState<EditingTarget>();

  if (personasQuery.isPending) return <PersonaListSkeleton />;

  if (!personasQuery.data) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16">
        <p className="text-sm break-keep text-muted-foreground">대화 프로필을 불러오지 못했어요.</p>
        <Button type="button" variant="outline" onClick={() => void personasQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  return <PersonaListSection personaList={personasQuery.data} editing={editing} onEditingChange={setEditing} />;
}

type PersonaListSectionProps = {
  personaList: PersonaList;
  editing: EditingTarget;
  onEditingChange: (next: EditingTarget) => void;
};

function PersonaListSection({ personaList, editing, onEditingChange }: PersonaListSectionProps) {
  const limitHintId = useId();
  const createHeadingId = useId();
  const { items, defaultPersonaId, maxCount } = personaList;
  const isAtLimit = items.length >= maxCount;
  const isCreating = editing?.kind === "create";

  function handleCreateClick() {
    if (isAtLimit) return;
    onEditingChange({ kind: "create" });
  }

  const createForm = (
    <section aria-labelledby={createHeadingId} className="flex flex-col gap-4 rounded-xl border border-border p-4">
      <h2 id={createHeadingId} className="text-lg font-semibold text-foreground">
        새 대화 프로필
      </h2>
      <CreatePersonaForm
        defaultPersonaId={defaultPersonaId}
        onCreated={() => onEditingChange(undefined)}
        onCancel={() => onEditingChange(undefined)}
      />
    </section>
  );

  if (items.length === 0) {
    return isCreating ? (
      createForm
    ) : (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center">
        <p className="text-lg font-semibold text-foreground">아직 대화 프로필이 없어요</p>
        <p className="text-sm break-keep text-muted-foreground">
          이름과 성별, 나에 대한 설명을 적어 두면 캐릭터가 그걸 알고 대화해요.
        </p>
        <Button type="button" variant="outline" className="mt-2" onClick={handleCreateClick}>
          <Plus aria-hidden />첫 프로필 만들기
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground tabular-nums">
            {items.length}/{maxCount}개
          </p>
          {!isCreating && (
            <Button
              type="button"
              variant="outline"
              aria-disabled={isAtLimit}
              aria-describedby={isAtLimit ? limitHintId : undefined}
              className="aria-disabled:opacity-65"
              onClick={handleCreateClick}
            >
              <Plus aria-hidden />새 프로필
            </Button>
          )}
        </div>
        {isAtLimit && !isCreating && (
          <p id={limitHintId} className="text-xs break-keep text-muted-foreground">
            대화 프로필은 최대 {maxCount}개까지 만들 수 있어요. 새로 만들려면 하나를 삭제해 주세요.
          </p>
        )}
      </div>

      {isCreating && createForm}

      <ul className="flex flex-col gap-2">
        {items.map((persona) => {
          const isDefault = persona.id === defaultPersonaId;
          const isEditing = editing?.kind === "edit" && editing.personaId === persona.id;

          return (
            <li key={persona.id} className="rounded-xl border border-border">
              {isEditing ? (
                <div className="p-4">
                  <EditPersonaForm
                    persona={persona}
                    onSaved={() => onEditingChange(undefined)}
                    onCancel={() => onEditingChange(undefined)}
                  />
                </div>
              ) : (
                <div className="flex items-start gap-3 py-3 pr-2 pl-4">
                  <PersonaSummary persona={persona} isDefault={isDefault} className="flex-1 py-0.5" />
                  <PersonaActionMenu
                    persona={persona}
                    isDefault={isDefault}
                    onEdit={() => onEditingChange({ kind: "edit", personaId: persona.id })}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** 진행 표시라 `animate-pulse`를 가드하지 않는다(DESIGN.md §5 Motion 예외). 행 높이는 두 줄 요약 행과 같다. */
function PersonaListSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-2">
      {[0, 1].map((index) => (
        <div key={index} className="h-16 animate-pulse rounded-xl bg-muted" />
      ))}
    </div>
  );
}
