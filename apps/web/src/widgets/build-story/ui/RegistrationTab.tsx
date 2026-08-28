import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
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
import { X } from "lucide-react";
import { useState } from "react";
import { Controller, useWatch, type UseFormReturn } from "react-hook-form";

import { useGenreListQuery } from "@/entities/content";
import type { StoryBuilderFormValues } from "@/features/build-story";

const TARGET_OPTIONS: { value: "female" | "male" | "all"; label: string }[] = [
  { value: "female", label: "여성향" },
  { value: "male", label: "남성향" },
  { value: "all", label: "공용" },
];

const VISIBILITY_OPTIONS: { value: "public" | "link" | "private"; label: string }[] = [
  { value: "public", label: "전체공개" },
  { value: "link", label: "링크공개" },
  { value: "private", label: "비공개" },
];

/** techspec-builder-story.md §1.6 — 등록 설명/장르/타겟/해시태그/공개범위 메타데이터. 캐릭터 빌더
 * `DetailTab`(US-093)과 동일한 필드/UI 구성(`registration` 스키마가 이미 US-092에서 공유 모양으로
 * 구현돼 있다) — 장르 목록은 하드코딩 enum이 아니라 GET /genres 서버 조회 결과로 select 옵션을 구성한다. */
export function RegistrationTab({ form }: { form: UseFormReturn<StoryBuilderFormValues> }) {
  const { register, control, setValue } = form;
  const genreListQuery = useGenreListQuery();
  const hashtags = useWatch({ control, name: "registration.hashtags" });
  const [hashtagInput, setHashtagInput] = useState("");

  function addHashtag() {
    const trimmed = hashtagInput.trim();
    setHashtagInput("");
    if (!trimmed || hashtags.includes(trimmed)) return;
    setValue("registration.hashtags", [...hashtags, trimmed], { shouldValidate: true });
  }

  function removeHashtag(hashtag: string) {
    setValue(
      "registration.hashtags",
      hashtags.filter((tag) => tag !== hashtag),
      { shouldValidate: true },
    );
  }

  return (
    <div className="flex flex-col gap-6 py-6">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-registration-description">등록 설명 *</Label>
        <Textarea
          id="story-registration-description"
          placeholder="스토리를 목록에서 소개할 설명을 입력해주세요"
          rows={4}
          {...register("registration.description")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-registration-genre">장르 *</Label>
        <Controller
          control={control}
          name="registration.genre"
          render={({ field }) => (
            <Select value={field.value ?? ""} onValueChange={field.onChange}>
              <SelectTrigger id="story-registration-genre" className="w-full">
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
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium">타겟 *</span>
        <Controller
          control={control}
          name="registration.target"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              value={field.value ?? ""}
              onValueChange={(value) => value && field.onChange(value)}
              aria-label="타겟"
            >
              {TARGET_OPTIONS.map((option) => (
                <ToggleGroupItem key={option.value} value={option.value} aria-label={option.label}>
                  {option.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="story-registration-hashtag-input">해시태그</Label>
        <div className="flex gap-2">
          <Input
            id="story-registration-hashtag-input"
            placeholder="해시태그를 입력 후 추가해주세요"
            value={hashtagInput}
            onChange={(event) => setHashtagInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              event.preventDefault();
              addHashtag();
            }}
          />
          <Button type="button" variant="secondary" onClick={addHashtag}>
            추가
          </Button>
        </div>
        {hashtags.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {hashtags.map((hashtag) => (
              <span
                key={hashtag}
                className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground"
              >
                #{hashtag}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-4"
                  aria-label={`${hashtag} 해시태그 삭제`}
                  onClick={() => removeHashtag(hashtag)}
                >
                  <X aria-hidden className="size-3" />
                </Button>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm leading-none font-medium">공개범위 *</span>
        <Controller
          control={control}
          name="registration.visibility"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              value={field.value}
              onValueChange={(value) => value && field.onChange(value)}
              aria-label="공개범위"
            >
              {VISIBILITY_OPTIONS.map((option) => (
                <ToggleGroupItem key={option.value} value={option.value} aria-label={option.label}>
                  {option.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      </div>
    </div>
  );
}
