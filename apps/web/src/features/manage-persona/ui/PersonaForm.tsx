import { useId } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";

import { PERSONA_DESCRIPTION_MAX_LENGTH, type Persona } from "@/entities/persona";

import { useCreatePersonaMutation } from "../api/useCreatePersonaMutation";
import { useUpdatePersonaMutation } from "../api/useUpdatePersonaMutation";
import { formToCreateRequest, formToUpdateRequest } from "../model/formToServer";
import { personaErrorMessage } from "../model/personaErrorMessage";
import { PERSONA_GENDER_OPTIONS, PERSONA_GENDER_OPTION_LABEL, toPersonaGenderOption } from "../model/personaGenderOption";
import { personaFormSchema, type PersonaFormValues } from "../model/schema";
import { createFormDefaults, serverToForm } from "../model/serverToForm";

type CreatePersonaFormProps = {
  /** `GET /me/personas`의 `defaultPersonaId` — "기본으로 지정" 체크박스의 초기값을 정한다(UP-23). */
  defaultPersonaId: string | null;
  /** Promise를 돌려주면 그것이 끝날 때까지 폼이 "저장 중"으로 남는다 — 생성 뒤 후속 요청(방 적용 등)이 도는
   * 동안 다시 제출해 같은 프로필을 또 만들지 않게(review-s7.md 🟡-1). 거부하면 폼 루트 에러가 되므로 후속
   * 실패는 호출부에서 처리하고 resolve한다. */
  onCreated: (persona: Persona) => void | Promise<void>;
  onCancel: () => void;
};

/** 관리 페이지와 대화방 "새로 만들기"가 같은 폼·같은 규칙을 쓴다(persona-goal-prompt.md §3-3 UP-23). */
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

type PersonaFormBodyProps = {
  defaultValues: PersonaFormValues;
  /** 생성 폼에만 "기본으로 지정"이 있다 — 편집에서 기본을 바꾸는 길은 목록의 메뉴다(`PUT /me/default-persona`). */
  isCreate: boolean;
  submitLabel: string;
  onValidSubmit: (values: PersonaFormValues) => Promise<void>;
  onCancel: () => void;
};

function PersonaFormBody({ defaultValues, isCreate, submitLabel, onValidSubmit, onCancel }: PersonaFormBodyProps) {
  const fieldId = useId();
  const form = useForm<PersonaFormValues>({
    resolver: zodResolver(personaFormSchema),
    defaultValues,
  });
  const { errors, isSubmitting } = form.formState;
  const descriptionLength = useWatch({ control: form.control, name: "description" }).length;

  const nameId = `${fieldId}-name`;
  const descriptionId = `${fieldId}-description`;
  const setAsDefaultId = `${fieldId}-default`;

  async function handleValidSubmit(values: PersonaFormValues) {
    form.clearErrors("root");
    try {
      await onValidSubmit(values);
    } catch (error) {
      form.setError("root", { message: personaErrorMessage(error) });
    }
  }

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        // 로딩 중 `disabled`는 누른 버튼의 포커스를 날린다 — `aria-disabled` + 여기서 막는다(apps/web/CLAUDE.md §포커스).
        if (isSubmitting) return;
        void form.handleSubmit(handleValidSubmit)(event);
      }}
    >
      {errors.root && (
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          {errors.root.message}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={nameId}>이름</Label>
        {/* persona-goal-prompt.md UP-6·R-11 — 빈칸으로 시작한다. 닉네임으로 미리 채우지 않는다. */}
        {/* 폼은 언제나 사용자가 버튼을 눌러 연다 — 그 버튼이 사라지며 포커스가 `<body>`로 떨어지지 않게 첫 칸이 받는다. */}
        <Input
          id={nameId}
          autoFocus
          autoComplete="off"
          placeholder="캐릭터가 나를 부를 이름"
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? `${nameId}-error` : undefined}
          {...form.register("name")}
        />
        {errors.name && (
          <p id={`${nameId}-error`} role="alert" className="text-xs text-destructive-text">
            {errors.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span id={`${fieldId}-gender`} className="text-sm font-medium text-foreground">
          성별
        </span>
        <Controller
          control={form.control}
          name="gender"
          render={({ field }) => (
            // `variant="list"` 틴트 — 아래 제출 버튼이 이 화면의 `primary` 솔리드 하나다(DESIGN.md §2 밝기 예산).
            // `hover:bg-secondary` — 프리미티브의 `hover:bg-muted`는 모달(`popover`) 위에서 표면과 같은 값이라
            // 사라진다(대화방 선택 모달에서도 이 폼을 쓴다).
            <ToggleGroup
              type="single"
              variant="list"
              value={field.value}
              onValueChange={(value) => {
                const option = toPersonaGenderOption(value);
                if (option) field.onChange(option);
              }}
              aria-labelledby={`${fieldId}-gender`}
              className="flex-wrap gap-2"
            >
              {PERSONA_GENDER_OPTIONS.map((option) => (
                <ToggleGroupItem key={option} value={option} className="h-9 px-3.5 hover:bg-secondary">
                  {PERSONA_GENDER_OPTION_LABEL[option]}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <Label htmlFor={descriptionId}>
            설명 <span className="font-normal text-muted-foreground">(선택)</span>
          </Label>
          <span id={`${descriptionId}-count`} className="text-xs text-muted-foreground tabular-nums">
            {descriptionLength}/{PERSONA_DESCRIPTION_MAX_LENGTH}
          </span>
        </div>
        <Textarea
          id={descriptionId}
          rows={4}
          placeholder="캐릭터가 알았으면 하는 나 — 나이, 직업, 성격, 말투 등"
          aria-invalid={!!errors.description}
          aria-describedby={
            errors.description ? `${descriptionId}-error ${descriptionId}-count` : `${descriptionId}-count`
          }
          {...form.register("description")}
        />
        {errors.description && (
          <p id={`${descriptionId}-error`} role="alert" className="text-xs text-destructive-text">
            {errors.description.message}
          </p>
        )}
      </div>

      {isCreate && (
        <Controller
          control={form.control}
          name="setAsDefault"
          render={({ field }) => (
            <div className="flex items-start gap-2.5">
              <Checkbox
                id={setAsDefaultId}
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                aria-describedby={`${setAsDefaultId}-hint`}
                className="mt-0.5"
              />
              <div className="flex flex-col gap-0.5">
                <Label htmlFor={setAsDefaultId}>기본 프로필로 지정</Label>
                {/* persona-goal-prompt.md UP-7 파생 ① — 기본은 새 방에만 들어간다. R-18: 켜진 채 시작하는
                    이유(자동 기본)를 사용자가 알 수 있게 무엇이 바뀌는지 적는다. */}
                <p id={`${setAsDefaultId}-hint`} className="text-xs break-keep text-muted-foreground">
                  새로 여는 대화방이 이 프로필로 시작해요. 지금 있는 대화방은 그대로예요.
                </p>
              </div>
            </div>
          )}
        />
      )}

      {/* 취소 먼저, 실행 나중(packages/ui/CLAUDE.md — 확인 모달 버튼 순서와 같은 DOM 순서).
          `hover:bg-secondary` — 성별 토글과 같은 이유: ghost의 `hover:bg-muted`는 모달(`popover`) 위에서
          표면과 같은 값이라 hover가 1.000:1로 사라졌다(persona-progress.md S8 🟡-2). */}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" className="hover:bg-secondary" onClick={onCancel}>
          취소
        </Button>
        <Button type="submit" aria-disabled={isSubmitting} className="aria-disabled:opacity-65">
          {isSubmitting ? "저장 중..." : submitLabel}
        </Button>
      </div>
    </form>
  );
}
