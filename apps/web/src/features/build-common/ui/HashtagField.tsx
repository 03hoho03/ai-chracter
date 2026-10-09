import type { ReactNode } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import {
  HASHTAG_LIMIT_MESSAGE,
  hashtagRefusal,
  MAX_HASHTAG_LENGTH,
  MAX_HASHTAGS,
  normalizeHashtag,
} from "@/entities/content";

import { KeywordChipField } from "./KeywordChipField";

/** 두 빌더 폼이 같은 자리에 둔 해시태그 목록만 본다. */
type HashtagFormValues = { registration: { hashtags: string[] } };

type HashtagFieldProps = {
  /** 입력칸·안내 문장의 id 접두. 빌더마다 다르다. */
  idPrefix: string;
  /** 화면 라벨. */
  labelContent: ReactNode;
};

/**
 * 두 빌더의 등록 탭 해시태그 칸. 입력할 때 앞에 붙인 `#` 과 앞뒤 공백을 지우고, 대소문자만 다른 태그나 상한(개수·글자
 * 수)을 넘는 태그는 넣지 않고 이유를 보인다 — 자동저장은 발행 검사를 거치지 않아 서버가 거절할 값이 폼에 들어가면 그
 * 초안 저장 전체가 멈춘다. 이미 저장된 태그는 고치지 않는다.
 */
export function HashtagField({ idPrefix, labelContent }: HashtagFieldProps) {
  const {
    control,
    setValue,
    formState: { errors },
  } = useFormContext<HashtagFormValues>();
  const hashtags = useWatch({ control, name: "registration.hashtags" });

  return (
    <KeywordChipField
      idPrefix={idPrefix}
      label="해시태그"
      labelContent={labelContent}
      chipNoun="해시태그"
      placeholder="해시태그를 입력 후 추가해주세요"
      keywords={hashtags}
      limit={MAX_HASHTAGS}
      limitReason={HASHTAG_LIMIT_MESSAGE}
      itemMaxLength={MAX_HASHTAG_LENGTH}
      normalize={normalizeHashtag}
      validate={(tag) => hashtagRefusal(tag, hashtags)}
      onAdd={(tag) => setValue("registration.hashtags", [...hashtags, tag], { shouldValidate: true })}
      onRemove={(tag) =>
        setValue(
          "registration.hashtags",
          hashtags.filter((item) => item !== tag),
          { shouldValidate: true },
        )
      }
      chipStyle="filled"
      chipPrefix="#"
      error={errors.registration?.hashtags?.message}
      fieldPath="registration.hashtags"
    />
  );
}
