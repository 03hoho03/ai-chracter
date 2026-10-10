import { useQueryClient } from "@tanstack/react-query";

import { choosePersonaForNewRoom, type NewRoomPersonaChoice } from "./choosePersonaForNewRoom";
import { FirstPersonaNameModal } from "../ui/FirstPersonaNameModal";

type ChooseOptions = {
  /** 이름 모달을 띄우기 직전에 부른다 — 판정하는 동안 돌던 진행 표시를 모달 뒤에 남기지 않게 끈다. */
  onBeforeNameModal?: () => void;
};

/** 앱의 `QueryClient` 와 이름 모달로 `choosePersonaForNewRoom` 을 부르는 함수를 준다. */
export function useChoosePersonaForNewRoom() {
  const queryClient = useQueryClient();

  return function choose(chosenPersonaId?: string, options?: ChooseOptions): Promise<NewRoomPersonaChoice> {
    return choosePersonaForNewRoom(queryClient, chosenPersonaId, () => {
      options?.onBeforeNameModal?.();
      return FirstPersonaNameModal.call();
    });
  };
}
