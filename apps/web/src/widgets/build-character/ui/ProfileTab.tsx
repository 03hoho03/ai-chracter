import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Controller, useFormContext } from "react-hook-form";

import type { CharacterBuilderFormValues } from "@/features/build-character";
import { GeneratedImageField } from "@/features/select-generated-image";

/** techspec-builder-character.md §0 AC — 이름/한줄소개(필수 텍스트)와 대표 이미지(업로드/AI생성 선택).
 * `thumbnailUrl`은 초안 조회 응답의 표시 전용 값(builder-techspec.md §7) — 폼 필드가 아니라 초안
 * 재진입 시 이미지 필드를 채우기 위한 prop이다. */
export function ProfileTab({ thumbnailUrl }: { thumbnailUrl: string | null }) {
  const form = useFormContext<CharacterBuilderFormValues>();

  const {
    register,
    control,
    formState: { errors },
  } = form;

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-2" data-field-path="profile.image">
        <Label>대표 이미지 *</Label>
        <Controller
          control={control}
          name="profile.image"
          render={({ field }) => (
            <GeneratedImageField
              value={field.value}
              onChange={field.onChange}
              purpose="content-thumbnail"
              previewUrl={thumbnailUrl ?? undefined}
            />
          )}
        />
        {errors.profile?.image && (
          <p id="character-profile-image-error" role="alert" className="text-xs text-destructive-text">
            {errors.profile.image.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-profile-name">이름 *</Label>
        <Input
          id="character-profile-name"
          placeholder="캐릭터 이름을 입력해주세요"
          aria-invalid={!!errors.profile?.name}
          aria-describedby={errors.profile?.name ? "character-profile-name-error" : undefined}
          {...register("profile.name")}
        />
        {errors.profile?.name && (
          <p id="character-profile-name-error" role="alert" className="text-xs text-destructive-text">
            {errors.profile.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-profile-oneliner">한줄소개 *</Label>
        <Input
          id="character-profile-oneliner"
          placeholder="캐릭터를 한 줄로 소개해주세요"
          aria-invalid={!!errors.profile?.oneLiner}
          aria-describedby={errors.profile?.oneLiner ? "character-profile-oneliner-error" : undefined}
          {...register("profile.oneLiner")}
        />
        {errors.profile?.oneLiner && (
          <p id="character-profile-oneliner-error" role="alert" className="text-xs text-destructive-text">
            {errors.profile.oneLiner.message}
          </p>
        )}
      </div>
    </div>
  );
}
