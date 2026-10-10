import { Label } from "@ai-character-chat/ui/components/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Controller, useFormContext } from "react-hook-form";

import {
  MAX_DESCRIPTION_LENGTH,
  NOVEL_PERMISSION_FIELD_LABEL,
  NovelPermissionPicker,
  useGenreListQuery,
} from "@/entities/content";
import { useCreatorPayoutRate } from "@/entities/creator-payout";
import { hasEnabledFeature, useSessionQuery } from "@/entities/session";
import {
  TARGET_VALUES,
  VISIBILITY_VALUES,
  type CharacterBuilderFormValues,
  type Target,
  type Visibility,
} from "@/features/build-character";
import { FieldCharacterCount, HashtagField, useLimitedTextField } from "@/features/build-common";
import { BuilderTextarea } from "@/shared/ui/BuilderTextarea";
import { RequiredText } from "@/shared/ui/RequiredText";

import { CharacterMacroNotice } from "./CharacterMacroNotice";

// 값 목록(TARGET_VALUES/VISIBILITY_VALUES)은 스키마가 단일 소스다. 여기서는 그 배열을 map해
// 라벨만 매핑한다.
const TARGET_LABELS: Record<Target, string> = {
  female: "여성향",
  male: "남성향",
  all: "공용",
};

const VISIBILITY_LABELS: Record<Visibility, string> = {
  public: "전체공개",
  link: "링크공개",
  private: "비공개",
};

/** 등록 설명/장르/타겟/해시태그/공개범위/소설 만들기 허락 메타데이터. 장르 목록은
 * 하드코딩 enum이 아니라 GET /genres 서버 조회 결과로 select 옵션을 구성한다. */
export function DetailTab() {
  const form = useFormContext<CharacterBuilderFormValues>();

  const {
    control,
    formState: { errors },
  } = form;
  const genreListQuery = useGenreListQuery();
  const { data: me } = useSessionQuery();
  const payoutRate = useCreatorPayoutRate(hasEnabledFeature(me?.enabledFeatures, "creator_payout"));
  const description = useLimitedTextField<CharacterBuilderFormValues>("registration.description", MAX_DESCRIPTION_LENGTH);

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-detail-description"><RequiredText>등록 설명</RequiredText></Label>
        <BuilderTextarea
          id="character-detail-description"
          placeholder="캐릭터를 목록에서 소개할 설명을 입력해주세요"
          rows={5}
          aria-invalid={!!errors.registration?.description}
          aria-describedby={
            errors.registration?.description
              ? "character-detail-description-count character-detail-description-error"
              : "character-detail-description-count"
          }
          {...description.registration}
        />
        <FieldCharacterCount
          id="character-detail-description-count"
          name={description.registration.name}
          max={MAX_DESCRIPTION_LENGTH}
          isTruncated={description.isTruncated}
        />
        <CharacterMacroNotice name="registration.description" />
        {errors.registration?.description && (
          <p id="character-detail-description-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.description.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="character-detail-genre"><RequiredText>장르</RequiredText></Label>
        <Controller
          control={control}
          name="registration.genre"
          render={({ field }) => (
            <Select value={field.value ?? ""} onValueChange={field.onChange}>
              <SelectTrigger
                id="character-detail-genre"
                ref={field.ref}
                className="w-full"
                aria-invalid={!!errors.registration?.genre}
                aria-describedby={errors.registration?.genre ? "character-detail-genre-error" : undefined}
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
          <p id="character-detail-genre-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.genre.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium"><RequiredText>타겟</RequiredText></span>
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
              aria-describedby={errors.registration?.target ? "character-detail-target-error" : undefined}
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
          <p id="character-detail-target-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.target.message}
          </p>
        )}
      </div>

      <HashtagField idPrefix="character-detail-hashtag" labelContent="해시태그" />

      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium"><RequiredText>공개범위</RequiredText></span>
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
              aria-describedby={errors.registration?.visibility ? "character-detail-visibility-error" : undefined}
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
          <p id="character-detail-visibility-error" role="alert" className="text-xs text-destructive-text">
            {errors.registration.visibility.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span id="character-detail-novel-permission-label" className="text-sm leading-none font-medium">
          {NOVEL_PERMISSION_FIELD_LABEL}
        </span>
        <Controller
          control={control}
          name="registration.novelPermission"
          render={({ field }) => (
            <NovelPermissionPicker
              ref={field.ref}
              value={field.value}
              onValueChange={field.onChange}
              labelledBy="character-detail-novel-permission-label"
              earningRate={payoutRate}
            />
          )}
        />
      </div>
    </div>
  );
}
