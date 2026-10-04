import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Controller, useFormContext } from "react-hook-form";

import { toThumbnailAspect, toThumbnailAspectRatio } from "@/entities/content";
import { FieldLabelText, type StoryBuilderFormValues } from "@/features/build-story";
import { ImageCropModal } from "@/features/crop-image";
import { GeneratedImageField } from "@/features/select-generated-image";

import { MediaTagOutsideNotice } from "./MediaTagOutsideNotice";

type ProfileTabProps = {
  /** 폼이 지금 가진 대표 이미지의 표시 주소. 미리보기 카드와 같은 값을 셸이 정해 내려 준다. */
  thumbnailUrl: string | null;
  /** 업로드·갤러리 선택 결과를 셸에 알린다. 탭을 옮기면 이 탭이 언마운트되므로 방금 올리거나 고른 그림의
   * 주소는 셸이 쥔다. */
  onUploadComplete: (assetId: string, file: File) => void;
  onPick: (assetId: string, imageUrl: string) => void;
};

/** 이름/한줄소개(필수 텍스트)와 대표 이미지(업로드/AI생성 선택). */
export function ProfileTab({ thumbnailUrl, onUploadComplete, onPick }: ProfileTabProps) {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    register,
    control,
    formState: { errors },
  } = form;

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-2" data-field-path="profile.image">
        <Label><FieldLabelText field="profile.image" /></Label>
        <Controller
          control={control}
          name="profile.image"
          render={({ field }) => (
            <>
              <GeneratedImageField
                value={field.value}
                onChange={field.onChange}
                purpose="content-thumbnail"
                previewUrl={thumbnailUrl ?? undefined}
                onUploadComplete={onUploadComplete}
                onPick={onPick}
                previewAspect={toThumbnailAspect("story")}
                beforeUpload={(file) =>
                  ImageCropModal.call({ file, aspect: toThumbnailAspectRatio(toThumbnailAspect("story")) })
                }
              />
              {errors.profile?.image && (
                <p id="story-profile-image-error" role="alert" className="text-xs text-destructive-text">
                  {errors.profile.image.message}
                </p>
              )}
            </>
          )}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-profile-name"><FieldLabelText field="profile.name" /></Label>
        <Input
          id="story-profile-name"
          placeholder="스토리 이름을 입력해주세요"
          aria-invalid={!!errors.profile?.name}
          aria-describedby={errors.profile?.name ? "story-profile-name-error" : undefined}
          {...register("profile.name")}
        />
        {errors.profile?.name && (
          <p id="story-profile-name-error" role="alert" className="text-xs text-destructive-text">
            {errors.profile.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-profile-oneliner"><FieldLabelText field="profile.oneLiner" /></Label>
        <Input
          id="story-profile-oneliner"
          placeholder="스토리를 한 줄로 소개해주세요"
          aria-invalid={!!errors.profile?.oneLiner}
          aria-describedby={errors.profile?.oneLiner ? "story-profile-oneliner-error" : undefined}
          {...register("profile.oneLiner")}
        />
        <MediaTagOutsideNotice name="profile.oneLiner" />
        {errors.profile?.oneLiner && (
          <p id="story-profile-oneliner-error" role="alert" className="text-xs text-destructive-text">
            {errors.profile.oneLiner.message}
          </p>
        )}
      </div>
    </div>
  );
}
