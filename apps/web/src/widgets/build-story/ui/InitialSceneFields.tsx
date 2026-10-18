import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { useFormContext, useWatch } from "react-hook-form";

import { FieldCharacterCount, useLimitedTextField } from "@/features/build-common";
import { FieldLabelText, MAX_STORY_SCENE_FIELD_LENGTH, type StoryBuilderFormValues } from "@/features/build-story";

type InitialSceneFieldsProps = {
  /** 칸 id 접두어(시작설정 행의 안정 id). */
  id: string;
  index: number;
};

/**
 * 시작설정의 첫 장면(장소·시간) 두 칸. 설정 탭에서 장면 헤더를 켠 작품에만 보인다 — 끄면 칸을 숨기되 값은 지우지 않아 다시
 * 켜면 그대로 돌아오고, 숨은 동안의 자동저장도 들고 있던 값을 그대로 보낸다(RHF 는 숨은 칸의 값을 폼에 남긴다).
 *
 * 서버는 상한을 넘는 칸이 든 초안 저장을 통째로 거절하므로 두 칸 모두 입력 단계에서 상한에서 자른다.
 */
export function InitialSceneFields({ id, index }: InitialSceneFieldsProps) {
  const {
    control,
    formState: { errors },
  } = useFormContext<StoryBuilderFormValues>();
  const isEnabled = useWatch({ control, name: "storySetting.sceneHeaderEnabled" });
  const place = useLimitedTextField<StoryBuilderFormValues>(
    `startingSetups.${index}.initialScenePlace`,
    MAX_STORY_SCENE_FIELD_LENGTH,
  );
  const time = useLimitedTextField<StoryBuilderFormValues>(
    `startingSetups.${index}.initialSceneTime`,
    MAX_STORY_SCENE_FIELD_LENGTH,
  );
  const rowErrors = errors.startingSetups?.[index];

  if (!isEnabled) return null;

  const fields = [
    {
      key: "place",
      field: place,
      label: "startingSetups.*.initialScenePlace",
      placeholder: "예: 폐광 입구",
      error: rowErrors?.initialScenePlace,
    },
    {
      key: "time",
      field: time,
      label: "startingSetups.*.initialSceneTime",
      placeholder: "예: 해 질 녘",
      error: rowErrors?.initialSceneTime,
    },
  ] as const;

  return (
    <div
      role="group"
      aria-labelledby={`starting-setup-${id}-initial-scene-title`}
      className="flex flex-col gap-3 rounded-xl border border-border px-4 py-3"
    >
      <div className="flex flex-col gap-0.5">
        <p id={`starting-setup-${id}-initial-scene-title`} className="text-sm leading-none font-medium">
          첫 장면
        </p>
        <p id={`starting-setup-${id}-initial-scene-help`} className="text-sm break-keep text-muted-foreground">
          대화방을 열고 첫 응답이 오기 전까지 플레이어 화면 위 장면 줄에 보여요. 둘 다 비우면 첫 응답부터 장면이 보여요.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map(({ key, field, label, placeholder, error }) => {
          const inputId = `starting-setup-${id}-initial-scene-${key}`;
          return (
            <div key={key} className="flex min-w-0 flex-col gap-1.5">
              <Label htmlFor={inputId}>
                <FieldLabelText field={label} />
              </Label>
              <Input
                id={inputId}
                placeholder={placeholder}
                aria-invalid={!!error}
                aria-describedby={[
                  `starting-setup-${id}-initial-scene-help`,
                  `${inputId}-count`,
                  error ? `${inputId}-error` : undefined,
                ]
                  .filter(Boolean)
                  .join(" ")}
                {...field.registration}
              />
              <FieldCharacterCount
                id={`${inputId}-count`}
                name={field.registration.name}
                max={MAX_STORY_SCENE_FIELD_LENGTH}
                isTruncated={field.isTruncated}
              />
              {error && (
                <p id={`${inputId}-error`} role="alert" className="text-xs break-keep text-destructive-text">
                  {error.message}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
