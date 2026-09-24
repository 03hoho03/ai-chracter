import { useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { MoreHorizontal, Pencil, Star, StarOff, Trash2 } from "lucide-react";
import { toast } from "sonner";

import type { Persona } from "@/entities/persona";

import { useSetDefaultPersonaMutation } from "../api/useSetDefaultPersonaMutation";
import { personaErrorMessage } from "../model/personaErrorMessage";
import { DeletePersonaModal } from "./DeletePersonaModal";

type PersonaActionMenuProps = {
  persona: Persona;
  isDefault: boolean;
  /** 편집은 목록 행을 폼으로 바꾸는 인라인 편집이라(apps/web/CLAUDE.md "인라인 편집 우선") 상태를 호출부가 쥔다. */
  onEdit: () => void;
};

/** 관리 페이지 한 행의 ⋯ 메뉴 — 편집 · 기본 지정/해제 · 삭제. */
export function PersonaActionMenu({ persona, isDefault, onEdit }: PersonaActionMenuProps) {
  const setDefaultMutation = useSetDefaultPersonaMutation();
  // 편집을 고르면 이 행이 폼으로 바뀌어 트리거가 언마운트된다. 그때 Radix가 닫힘 포커스를 (사라진) 트리거로
  // 돌려주면 폼 첫 칸의 autoFocus를 빼앗으므로 그 한 번만 막는다.
  const isEditSelectedRef = useRef(false);

  function handleToggleDefault() {
    if (setDefaultMutation.isPending) return;
    setDefaultMutation.mutate(isDefault ? null : persona.id, {
      onSuccess: () => toast.success(isDefault ? "기본 프로필을 해제했어요." : "기본 프로필로 지정했어요."),
      onError: (error) => toast.error(personaErrorMessage(error)),
    });
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`${persona.name} 프로필 메뉴`}
          // 인라인 편집을 닫을 때 관리 페이지가 포커스를 돌려줄 자리(PersonasPage `closeFormAndRestoreFocus`).
          data-persona-menu-trigger={persona.id}
          className="shrink-0 hover:bg-secondary aria-expanded:bg-secondary"
        >
          <MoreHorizontal aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        collisionPadding={8}
        className="w-auto"
        onCloseAutoFocus={(event) => {
          if (!isEditSelectedRef.current) return;
          isEditSelectedRef.current = false;
          event.preventDefault();
        }}
      >
        <DropdownMenuItem
          onSelect={() => {
            isEditSelectedRef.current = true;
            onEdit();
          }}
        >
          <Pencil aria-hidden />
          편집
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleToggleDefault}>
          {isDefault ? <StarOff aria-hidden /> : <Star aria-hidden />}
          {isDefault ? "기본 해제" : "기본으로 지정"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => void DeletePersonaModal.call({ persona, isDefault })}>
          <Trash2 aria-hidden />
          삭제
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
