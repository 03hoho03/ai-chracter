import { toast } from "sonner";

import { PersonaToggleList, type PersonaList } from "@/entities/persona";

import { useSetRoomPersonaMutation } from "../api/useSetRoomPersonaMutation";

type RoomPersonaPickerProps = {
  roomId: string;
  /** 방 상세 캐시의 `personaId`. undefined = "선택 안 함". */
  currentPersonaId: string | undefined;
  personaList: PersonaList;
  onChanged: () => void;
};

/** 대화방의 대화 프로필 목록("선택 안 함" 포함). 누르면 바로 `PUT`한다 — 확인 단계가 없는 이유는 되돌리기가
 * 같은 동작 한 번이고 내가 보낸 메시지는 바뀌지 않기 때문이다(작품 글 속 이름은 바로, 캐릭터는 다음 턴부터 반영). */
export function RoomPersonaPicker({ roomId, currentPersonaId, personaList, onChanged }: RoomPersonaPickerProps) {
  const setRoomPersonaMutation = useSetRoomPersonaMutation(roomId);
  const selectedPersonaId = currentPersonaId ?? null;

  function handleValueChange(personaId: string | null) {
    if (personaId === selectedPersonaId || setRoomPersonaMutation.isPending) return;
    setRoomPersonaMutation.mutate(personaId, {
      onSuccess: () => {
        toast.success("대화 프로필을 바꿨어요. 캐릭터는 다음 대화부터 알아요.");
        onChanged();
      },
      onError: () => toast.error("대화 프로필을 바꾸지 못했어요. 잠시 후 다시 시도해주세요."),
    });
  }

  return (
    <PersonaToggleList
      personaList={personaList}
      value={selectedPersonaId}
      onValueChange={handleValueChange}
      includeNone
      aria-label="이 대화방의 대화 프로필"
      aria-busy={setRoomPersonaMutation.isPending}
    />
  );
}
