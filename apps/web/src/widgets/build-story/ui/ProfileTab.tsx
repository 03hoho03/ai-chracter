import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Controller, type UseFormReturn } from "react-hook-form";

import type { StoryBuilderFormValues } from "../../../features/build-story";
import { GeneratedImageField } from "../../../features/select-generated-image";

/** techspec-builder-story.md §0 AC — 이름/한줄소개(필수 텍스트)와 대표 이미지(업로드/AI생성 선택). */
export function ProfileTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
  const { register, control } = form;

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-2">
        <Label>대표 이미지 *</Label>
        <Controller
          control={control}
          name="profile.image"
          render={({ field }) => (
            <GeneratedImageField value={field.value} onChange={field.onChange} purpose="content-thumbnail" />
          )}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-profile-name">이름 *</Label>
        <Input
          id="story-profile-name"
          placeholder="스토리 이름을 입력해주세요"
          {...register("profile.name")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-profile-oneliner">한줄소개 *</Label>
        <Input
          id="story-profile-oneliner"
          placeholder="스토리를 한 줄로 소개해주세요"
          {...register("profile.oneLiner")}
        />
      </div>
    </div>
  );
}
