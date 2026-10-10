import { useId, useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { MoreHorizontal, Pencil, Star, Trash2 } from "lucide-react";
import { toast } from "sonner";

import type { Persona } from "@/entities/persona";

import { useSetDefaultPersonaMutation } from "../api/useSetDefaultPersonaMutation";
import { personaErrorMessage } from "../model/personaErrorMessage";
import { DeletePersonaModal } from "./DeletePersonaModal";

type PersonaActionMenuProps = {
  persona: Persona;
  isDefault: boolean;
  /** 남은 프로필이 이것 하나다 — 서버가 마지막 하나의 삭제를 거절하므로 메뉴에서 미리 막고 사유를 보인다. */
  isLastPersona: boolean;
  /** 편집은 목록 행을 폼으로 바꾸는 인라인 편집이라(apps/web/CLAUDE.md "인라인 편집 우선") 상태를 호출부가 쥔다. */
  onEdit: () => void;
};

/** 관리 페이지 한 행의 ⋯ 메뉴 — 편집 · 기본 지정 · 삭제. 기본을 비우는 항목은 없다 — 프로필이 있으면 기본이 늘 하나
 * 있어야 해서(서버가 비우기를 거절한다) 기본을 바꾸려면 다른 프로필을 기본으로 지정한다. */
export function PersonaActionMenu({ persona, isDefault, isLastPersona, onEdit }: PersonaActionMenuProps) {
  const setDefaultMutation = useSetDefaultPersonaMutation();
  const deleteBlockedReasonId = useId();
  // 편집을 고르면 이 행이 폼으로 바뀌어 트리거가 언마운트된다. 그때 Radix가 닫힘 포커스를 (사라진) 트리거로
  // 돌려주면 폼 첫 칸의 autoFocus를 빼앗으므로 그 한 번만 막는다.
  const isEditSelectedRef = useRef(false);

  function handleSetDefault() {
    if (setDefaultMutation.isPending) return;
    setDefaultMutation.mutate(persona.id, {
      onSuccess: () => toast.success("기본 프로필로 지정했어요."),
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
        {!isDefault && (
          <DropdownMenuItem onSelect={handleSetDefault}>
            <Star aria-hidden />
            기본으로 지정
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        {/* 막힌 삭제는 `disabled` 가 아니라 `aria-disabled` 다 — 순회에 남아 이름과 사유가 함께 읽히고, 눌러도 메뉴가
            닫히지 않아 사유가 그 자리에 남는다(apps/web/CLAUDE.md 메뉴 · 모달 절). */}
        <DropdownMenuItem
          variant="destructive"
          aria-disabled={isLastPersona || undefined}
          aria-describedby={isLastPersona ? deleteBlockedReasonId : undefined}
          onSelect={(event) => {
            if (isLastPersona) {
              event.preventDefault();
              return;
            }
            void DeletePersonaModal.call({ persona, isDefault });
          }}
        >
          <Trash2 aria-hidden />
          삭제
        </DropdownMenuItem>
        {/* 구분선을 넣지 않는다 — 다음 그룹의 머리가 아니라 바로 위 항목의 사유다. */}
        {isLastPersona && (
          <DropdownMenuLabel id={deleteBlockedReasonId} className="max-w-52 break-keep">
            마지막 대화 프로필은 지울 수 없어요. 다른 프로필을 먼저 만들어 주세요.
          </DropdownMenuLabel>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
