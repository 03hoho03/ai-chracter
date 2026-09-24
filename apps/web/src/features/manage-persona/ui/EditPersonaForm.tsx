import type { Persona } from "@/entities/persona";

import { useUpdatePersonaMutation } from "../api/useUpdatePersonaMutation";
import { formToUpdateRequest } from "../model/formToServer";
import { serverToForm } from "../model/serverToForm";
import { PersonaFormBody } from "./PersonaFormBody";

type EditPersonaFormProps = {
  persona: Persona;
  onSaved: (persona: Persona) => void;
  onCancel: () => void;
};

export function EditPersonaForm({ persona, onSaved, onCancel }: EditPersonaFormProps) {
  const updateMutation = useUpdatePersonaMutation();

  return (
    <PersonaFormBody
      defaultValues={serverToForm(persona)}
      isCreate={false}
      submitLabel="저장"
      onCancel={onCancel}
      onValidSubmit={async (values) =>
        onSaved(await updateMutation.mutateAsync({ personaId: persona.id, payload: formToUpdateRequest(values) }))
      }
    />
  );
}
