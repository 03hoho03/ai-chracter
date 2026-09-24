import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { toast } from "sonner";

import { PersonaSummary, type PersonaList } from "@/entities/persona";

import { useSetRoomPersonaMutation } from "../api/useSetRoomPersonaMutation";

/** 토글 값으로 "선택 안 함"을 담는 표식. 프로필 id는 UUID라 겹치지 않는다. */
const NO_PERSONA_VALUE = "none";

const ITEM_CLASS = "h-auto min-h-11 w-full justify-start px-3.5 py-2.5 whitespace-normal hover:bg-secondary";

type RoomPersonaPickerProps = {
  roomId: string;
  /** 방 상세 캐시의 `personaId`. undefined = "선택 안 함". */
  currentPersonaId: string | undefined;
  personaList: PersonaList;
  onChanged: () => void;
};

/** 대화방의 대화 프로필 목록("선택 안 함" 포함). 누르면 바로 `PUT`한다 — 확인 단계가 없는 이유는 되돌리기가
 * 같은 동작 한 번이고 과거 메시지는 바뀌지 않기 때문이다(persona-goal-prompt.md UP-7, 다음 턴부터 반영).
 *
 * `variant="list"` — 넓은 행이 세로로 쌓인 선택지라 틴트로 표시한다(DESIGN.md §Toggles). `hover:bg-secondary`는
 * 프리미티브의 `hover:bg-muted`가 모달 표면(`popover`)과 같은 값이라 사라지는 것을 한 칸 올린다. */
export function RoomPersonaPicker({ roomId, currentPersonaId, personaList, onChanged }: RoomPersonaPickerProps) {
  const setRoomPersonaMutation = useSetRoomPersonaMutation(roomId);
  const selectedValue = currentPersonaId ?? NO_PERSONA_VALUE;

  function handleValueChange(value: string) {
    // 선택된 항목을 다시 누르면 Radix가 ""를 emit한다 — 선택은 언제나 정확히 하나라 무시한다.
    if (value === "" || value === selectedValue || setRoomPersonaMutation.isPending) return;
    setRoomPersonaMutation.mutate(value === NO_PERSONA_VALUE ? null : value, {
      onSuccess: () => {
        toast.success("대화 프로필을 바꿨어요. 다음 대화부터 반영돼요.");
        onChanged();
      },
      onError: () => toast.error("대화 프로필을 바꾸지 못했어요. 잠시 후 다시 시도해주세요."),
    });
  }

  return (
    <ToggleGroup
      type="single"
      variant="list"
      orientation="vertical"
      value={selectedValue}
      onValueChange={handleValueChange}
      aria-label="이 대화방의 대화 프로필"
      aria-busy={setRoomPersonaMutation.isPending}
      className="w-full flex-col gap-1.5"
    >
      <ToggleGroupItem value={NO_PERSONA_VALUE} className={ITEM_CLASS}>
        <span className="flex flex-col gap-0.5 text-left">
          <span className="text-sm font-medium">선택 안 함</span>
          <span className="text-xs break-keep text-muted-foreground">프로필 없이 대화해요.</span>
        </span>
      </ToggleGroupItem>
      {personaList.items.map((persona) => (
        <ToggleGroupItem key={persona.id} value={persona.id} className={ITEM_CLASS}>
          <PersonaSummary persona={persona} isDefault={persona.id === personaList.defaultPersonaId} />
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
