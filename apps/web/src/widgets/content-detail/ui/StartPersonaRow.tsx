import { useId, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@ai-character-chat/ui/components/dialog";
import { Plus } from "lucide-react";

import { PersonaToggleList, type Persona, type PersonaList } from "@/entities/persona";
import { CreatePersonaForm } from "@/features/manage-persona";

type StartPersonaRowProps = {
  personaList: PersonaList;
  /** 지금 시작하면 쓰일 프로필(`resolveStartPersona`). */
  startPersona: Persona;
  onSelect: (personaId: string) => void;
};

/**
 * 새 대화를 어느 대화 프로필로 시작할지 보이는 한 줄과, 바꾸기 모달. 하단 플레이 바는 그 화면의 단일 전환 액션만 담으므로
 * (DESIGN.md Navigation 절) 고르는 일은 바 밖, 본문의 시작 준비(시작 상황·내 대화 목록) 바로 뒤에 둔다.
 *
 * 고르기는 이 화면에서 시작할 대화에만 걸린다 — 기본 프로필은 바꾸지 않는다. 그래서 대화방 안의 선택과 달리 "선택 안 함"이
 * 없다(새 대화는 늘 프로필 하나로 시작한다). 모달 안에서 새로 만들 수 있고, 만든 것을 바로 고른다.
 */
export function StartPersonaRow({ personaList, startPersona, onSelect }: StartPersonaRowProps) {
  const headingId = useId();
  const nameId = useId();
  const limitHintId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [view, setView] = useState<"select" | "create">("select");
  const isAtLimit = personaList.items.length >= personaList.maxCount;
  const isCreateView = view === "create";

  function handleOpenChange(nextOpen: boolean) {
    setIsOpen(nextOpen);
    // 다시 열면 언제나 목록부터 보인다.
    if (nextOpen) setView("select");
  }

  function selectAndClose(personaId: string) {
    onSelect(personaId);
    setIsOpen(false);
  }

  return (
    <section aria-labelledby={headingId} className="flex items-center gap-3 border-t border-border pt-5">
      <h2 id={headingId} className="shrink-0 text-sm font-semibold text-foreground">
        대화 프로필
      </h2>
      <p id={nameId} className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
        {startPersona.name}
      </p>

      <Dialog open={isOpen} onOpenChange={handleOpenChange}>
        <DialogTrigger asChild>
          {/* `hover:bg-secondary` — outline 의 `hover:bg-muted` 는 상세 모달 표면(`popover`)과 같은 값이라 사라진다.
              터치에서는 누르는 높이만 40px 로 키운다. */}
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-describedby={`${headingId} ${nameId}`}
            className="hover:bg-secondary aria-expanded:bg-secondary pointer-coarse:h-10"
          >
            바꾸기
          </Button>
        </DialogTrigger>

        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{isCreateView ? "새 대화 프로필" : "대화 프로필 고르기"}</DialogTitle>
            <DialogDescription className="break-keep">
              {isCreateView
                ? "만들면 이번 대화에 바로 쓰여요."
                : "이번 대화에서 캐릭터가 알게 될 '나'예요. 기본 프로필은 그대로예요."}
            </DialogDescription>
          </DialogHeader>

          <DialogBody>
            {isCreateView ? (
              <CreatePersonaForm
                defaultPersonaId={personaList.defaultPersonaId}
                isFirstPersona={false}
                onCreated={(persona) => selectAndClose(persona.id)}
                onCancel={() => setView("select")}
              />
            ) : (
              <div className="flex flex-col gap-4">
                <PersonaToggleList
                  personaList={personaList}
                  value={startPersona.id}
                  // 지금 것을 다시 눌러도 닫는다 — 고른 것을 확인하는 동작으로 읽는다.
                  onValueChange={(personaId) => {
                    if (personaId !== null) selectAndClose(personaId);
                  }}
                  includeNone={false}
                  aria-label="이번 대화의 대화 프로필"
                />

                <div className="flex flex-col gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    aria-disabled={isAtLimit}
                    aria-describedby={isAtLimit ? limitHintId : undefined}
                    className="self-start hover:bg-secondary aria-disabled:opacity-65"
                    onClick={() => {
                      if (isAtLimit) return;
                      setView("create");
                    }}
                  >
                    <Plus aria-hidden />
                    새로 만들기
                  </Button>
                  {isAtLimit && (
                    <p id={limitHintId} className="text-xs break-keep text-muted-foreground">
                      대화 프로필은 최대 {personaList.maxCount}개까지 만들 수 있어요. 대화 프로필 화면에서 하나를 지우면
                      새로 만들 수 있어요.
                    </p>
                  )}
                </div>
              </div>
            )}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </section>
  );
}
