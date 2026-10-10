import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Controller, useFormContext } from "react-hook-form";

import {
  MAX_NAME_LENGTH,
  MAX_ONE_LINER_LENGTH,
  toThumbnailAspect,
  toThumbnailAspectRatio,
} from "@/entities/content";
import { FieldCharacterCount, useLimitedTextField } from "@/features/build-common";
import type { CharacterBuilderFormValues } from "@/features/build-character";
import { ImageCropModal } from "@/features/crop-image";
import { GeneratedImageField } from "@/features/select-generated-image";
import { RequiredText } from "@/shared/ui/RequiredText";

import { CharacterMacroNotice } from "./CharacterMacroNotice";

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
  const form = useFormContext<CharacterBuilderFormValues>();

  const {
    control,
    formState: { errors },
  } = form;
  const name = useLimitedTextField<CharacterBuilderFormValues>("profile.name", MAX_NAME_LENGTH);
  const oneLiner = useLimitedTextField<CharacterBuilderFormValues>("profile.oneLiner", MAX_ONE_LINER_LENGTH);

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-2" data-field-path="profile.image">
        <Label><RequiredText>대표 이미지</RequiredText></Label>
        <Controller
          control={control}
          name="profile.image"
          render={({ field }) => (
            <GeneratedImageField
              value={field.value}
              onChange={field.onChange}
              purpose="content-thumbnail"
              previewUrl={thumbnailUrl ?? undefined}
              onUploadComplete={onUploadComplete}
              onPick={onPick}
              inputRef={field.ref}
              previewAspect={toThumbnailAspect("character")}
              beforeUpload={(file) =>
                ImageCropModal.call({ file, aspect: toThumbnailAspectRatio(toThumbnailAspect("character")) })
              }
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
        <Label htmlFor="character-profile-name"><RequiredText>이름</RequiredText></Label>
        <Input
          id="character-profile-name"
          placeholder="예: 민유나"
          aria-invalid={!!errors.profile?.name}
          aria-describedby={errors.profile?.name ? "character-profile-name-count character-profile-name-error" : "character-profile-name-count"}
          {...name.registration}
        />
        <FieldCharacterCount
          id="character-profile-name-count"
          name={name.registration.name}
          max={MAX_NAME_LENGTH}
          isTruncated={name.isTruncated}
        />
        {errors.profile?.name && (
          <p id="character-profile-name-error" role="alert" className="text-xs text-destructive-text">
            {errors.profile.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-profile-oneliner"><RequiredText>한줄소개</RequiredText></Label>
        <Input
          id="character-profile-oneliner"
          placeholder="캐릭터를 한 줄로 소개해주세요"
          aria-invalid={!!errors.profile?.oneLiner}
          aria-describedby={errors.profile?.oneLiner ? "character-profile-oneliner-count character-profile-oneliner-error" : "character-profile-oneliner-count"}
          {...oneLiner.registration}
        />
        <FieldCharacterCount
          id="character-profile-oneliner-count"
          name={oneLiner.registration.name}
          max={MAX_ONE_LINER_LENGTH}
          isTruncated={oneLiner.isTruncated}
        />
        <CharacterMacroNotice name="profile.oneLiner" />
        {errors.profile?.oneLiner && (
          <p id="character-profile-oneliner-error" role="alert" className="text-xs text-destructive-text">
            {errors.profile.oneLiner.message}
          </p>
        )}
      </div>
    </div>
  );
}
