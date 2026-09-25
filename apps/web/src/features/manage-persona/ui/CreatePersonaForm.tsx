import type { Persona } from "@/entities/persona";

import { useCreatePersonaMutation } from "../api/useCreatePersonaMutation";
import { formToCreateRequest } from "../model/formToServer";
import { createFormDefaults } from "../model/serverToForm";
import { PersonaFormBody } from "./PersonaFormBody";

type CreatePersonaFormProps = {
  /** `GET /me/personas`의 `defaultPersonaId` — "기본으로 지정" 체크박스의 초기값을 정한다. */
  defaultPersonaId: string | null;
  /** Promise를 돌려주면 그것이 끝날 때까지 폼이 "저장 중"으로 남는다 — 생성 뒤 후속 요청(방 적용 등)이 도는
   * 동안 다시 제출해 같은 프로필을 또 만들지 않게. 거부하면 폼 루트 에러가 되므로 후속
   * 실패는 호출부에서 처리하고 resolve한다. */
  onCreated: (persona: Persona) => void | Promise<void>;
  onCancel: () => void;
};

/** 관리 페이지와 대화방 "새로 만들기"가 같은 폼·같은 규칙을 쓴다. */
export function CreatePersonaForm({ defaultPersonaId, onCreated, onCancel }: CreatePersonaFormProps) {
  const createMutation = useCreatePersonaMutation();

  return (
    <PersonaFormBody
      defaultValues={createFormDefaults(defaultPersonaId)}
      isCreate
      submitLabel="만들기"
      onCancel={onCancel}
      onValidSubmit={async (values) => {
        await onCreated(await createMutation.mutateAsync(formToCreateRequest(values)));
      }}
    />
  );
}
