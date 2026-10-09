import { Label } from "@ai-character-chat/ui/components/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef } from "react";
import { Controller, useFormContext } from "react-hook-form";

import { MAX_DESCRIPTION_LENGTH, NovelPermissionPicker, useGenreListQuery } from "@/entities/content";
import { useCreatorPayoutRate } from "@/entities/creator-payout";
import { hasEnabledFeature, useSessionQuery } from "@/entities/session";
import { FieldCharacterCount, HashtagField, useLimitedTextField } from "@/features/build-common";
import {
  FieldLabelText,
  TARGET_LABELS,
  TARGET_VALUES,
  VISIBILITY_LABELS,
  VISIBILITY_VALUES,
  type StoryBuilderFormValues,
} from "@/features/build-story";

import { MediaTagInsertButton } from "./MediaTagInsertButton";
import { StoryMacroNotice } from "./StoryMacroNotice";
import { UnknownMediaTagNotice } from "./UnknownMediaTagNotice";

/** 등록 설명/장르/타겟/해시태그/공개범위/소설 만들기 허락 메타데이터. 캐릭터 빌더
 * `DetailTab`과 동일한 필드/UI 구성(`registration` 스키마가 이미 공유 모양으로
 * 구현돼 있다) — 장르 목록은 하드코딩 enum이 아니라 GET /genres 서버 조회 결과로 select 옵션을 구성한다. */
export function RegistrationTab() {
  const form = useFormContext<StoryBuilderFormValues>();

  const {
    control,
    formState: { errors },
  } = form;
  const genreListQuery = useGenreListQuery();
  const { data: me } = useSessionQuery();
  const payoutRate = useCreatorPayoutRate(hasEnabledFeature(me?.enabledFeatures, "creator_payout"));
  const description = useLimitedTextField<StoryBuilderFormValues>("registration.description", MAX_DESCRIPTION_LENGTH);
  const descriptionField = description.registration;
  // "이미지 넣기"가 커서 자리를 읽을 입력창. `register` 의 ref 와 함께 건다.
  const descriptionRef = useRef<HTMLTextAreaElement | null>(null);

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor="story-registration-description"><FieldLabelText field="registration.description" /></Label>
          <MediaTagInsertButton
            name="registration.description"
            fieldLabel="등록 설명"
            textareaRef={descriptionRef}
            maxLength={MAX_DESCRIPTION_LENGTH}
          />
        </div>
        <Textarea
          id="story-registration-description"
          placeholder="스토리를 목록에서 소개할 설명을 입력해주세요"
          rows={4}
          aria-invalid={!!errors.registration?.description}
          aria-describedby={
            errors.registration?.description
              ? "story-registration-description-count story-registration-description-error"
              : "story-registration-description-count"
          }
          {...descriptionField}
          ref={(element) => {
            descriptionField.ref(element);
            descriptionRef.current = element;
          }}
        />
        <FieldCharacterCount
          id="story-registration-description-count"
          name={description.registration.name}
          max={MAX_DESCRIPTION_LENGTH}
          isTruncated={description.isTruncated}
        />
        <UnknownMediaTagNotice name="registration.description" />
        <StoryMacroNotice name="registration.description" />
        {errors.registration?.description && (
          <p id="story-registration-description-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.description.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-registration-genre"><FieldLabelText field="registration.genre" /></Label>
        <Controller
          control={control}
          name="registration.genre"
          render={({ field }) => (
            <Select value={field.value ?? ""} onValueChange={field.onChange}>
              <SelectTrigger
                id="story-registration-genre"
                ref={field.ref}
                className="w-full"
                aria-invalid={!!errors.registration?.genre}
                aria-describedby={errors.registration?.genre ? "story-registration-genre-error" : undefined}
              >
                <SelectValue placeholder="장르를 선택해주세요" />
              </SelectTrigger>
              <SelectContent>
                {genreListQuery.data?.map((genre) => (
                  <SelectItem key={genre.id} value={genre.id}>
                    {genre.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
        {errors.registration?.genre && (
          <p id="story-registration-genre-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.genre.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium"><FieldLabelText field="registration.target" /></span>
        <Controller
          control={control}
          name="registration.target"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              ref={field.ref}
              value={field.value ?? ""}
              onValueChange={(value) => value && field.onChange(value)}
              aria-label="타겟"
              aria-invalid={!!errors.registration?.target}
              aria-describedby={errors.registration?.target ? "story-registration-target-error" : undefined}
            >
              {TARGET_VALUES.map((value) => (
                <ToggleGroupItem
                  key={value}
                  value={value}
                  aria-label={TARGET_LABELS[value]}
                  className={cn(errors.registration?.target && "border-destructive ring-3 ring-destructive/20")}
                >
                  {TARGET_LABELS[value]}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
        {errors.registration?.target && (
          <p id="story-registration-target-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.target.message}
          </p>
        )}
      </div>

      <HashtagField idPrefix="story-registration-hashtag" labelContent={<FieldLabelText field="registration.hashtags" />} />

      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium"><FieldLabelText field="registration.visibility" /></span>
        <Controller
          control={control}
          name="registration.visibility"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              ref={field.ref}
              value={field.value}
              onValueChange={(value) => value && field.onChange(value)}
              aria-label="공개범위"
              aria-invalid={!!errors.registration?.visibility}
              aria-describedby={errors.registration?.visibility ? "story-registration-visibility-error" : undefined}
            >
              {VISIBILITY_VALUES.map((value) => (
                <ToggleGroupItem
                  key={value}
                  value={value}
                  aria-label={VISIBILITY_LABELS[value]}
                  className={cn(errors.registration?.visibility && "border-destructive ring-3 ring-destructive/20")}
                >
                  {VISIBILITY_LABELS[value]}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
        {errors.registration?.visibility && (
          <p id="story-registration-visibility-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.visibility.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span id="story-registration-novel-permission-label" className="text-sm leading-none font-medium">
          <FieldLabelText field="registration.novelPermission" />
        </span>
        <Controller
          control={control}
          name="registration.novelPermission"
          render={({ field }) => (
            <NovelPermissionPicker
              ref={field.ref}
              value={field.value}
              onValueChange={field.onChange}
              labelledBy="story-registration-novel-permission-label"
              earningRate={payoutRate}
            />
          )}
        />
      </div>
    </div>
  );
}
