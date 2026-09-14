import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { ChevronDown } from "lucide-react";
import { Controller, useFormContext } from "react-hook-form";

import type { SignUpFormValues } from "../model/signUpSchema";

const DETAIL_SUMMARY_TRIGGER_CLASSNAME =
  "flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none [&::-webkit-details-marker]:hidden";
const DETAIL_PANEL_CLASSNAME =
  "mt-2 flex flex-col gap-3 rounded-lg border border-border p-3 text-xs text-muted-foreground motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200";

/** 이메일 가입과 구글 온보딩 두 스텝이 이 fieldset을 바이트 단위로 똑같이 갖고 있어 한 벌로 묶었다 —
 * 문구·링크 수정이 한쪽에만 적용되는 사고를 막는 게 목적이다. `GuardianConsentStep`과 같은 결로
 * 폼은 prop이 아니라 `FormProvider` 컨텍스트에서 읽는다(두 스텝 모두 같은 `SignUpFormValues`를 쓴다).
 *
 * legal-revision-goal-prompt.md LR-1·LR-4 — 동의는 약관/수집·이용/국외이전 셋으로 나뉜다("개인정보
 * 처리방침 동의"라는 라벨은 버린다 — 처리방침은 동의 대상이 아니라 게재 대상이다). 수집·이용과
 * 국외이전 두 항목은 개인정보보호법 제15조 제2항·제28조의8 제2항이 요구하는 고지사항을 접이식
 * 요약으로 함께 보여준다. legal-revision-goal-prompt.md LR-21 — 접이식은 `packages/ui`에 없는
 * Accordion을 새로 들이지 않고 네이티브 `<details>`를 쓴다. */
export function LegalConsentFields() {
  const form = useFormContext<SignUpFormValues>();

  const {
    control,
    setValue,
    formState: { errors },
  } = form;
  const [termsAgreed, privacyAgreed, transferAgreed] = form.watch([
    "termsAgreed",
    "privacyAgreed",
    "transferAgreed",
  ]);

  return (
    <fieldset className="flex flex-col gap-3 rounded-lg border border-border p-4">
      <legend className="sr-only">약관 동의</legend>
      <label className="flex items-center gap-2 text-sm font-medium text-foreground">
        <Checkbox
          checked={termsAgreed && privacyAgreed && transferAgreed}
          onCheckedChange={(checked) => {
            setValue("termsAgreed", checked === true, { shouldValidate: true });
            setValue("privacyAgreed", checked === true, { shouldValidate: true });
            setValue("transferAgreed", checked === true, { shouldValidate: true });
          }}
        />
        전체 동의
      </label>

      <div className="flex flex-col gap-3 border-t border-border pt-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between gap-2">
            <Controller
              name="termsAgreed"
              control={control}
              render={({ field }) => (
                <label className="flex items-center gap-2 text-sm text-foreground">
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(checked) => field.onChange(checked === true)}
                    aria-invalid={!!errors.termsAgreed}
                  />
                  (필수) 이용약관 동의
                </label>
              )}
            />
            <a
              href="/terms"
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:underline"
            >
              이용약관 보기
            </a>
          </div>
          {errors.termsAgreed && (
            <p role="alert" className="pl-6 text-xs text-destructive-text">
              {errors.termsAgreed.message}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between gap-2">
            <Controller
              name="privacyAgreed"
              control={control}
              render={({ field }) => (
                <label className="flex items-center gap-2 text-sm text-foreground">
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(checked) => field.onChange(checked === true)}
                    aria-invalid={!!errors.privacyAgreed}
                  />
                  (필수) 개인정보 수집·이용 동의
                </label>
              )}
            />
            <a
              href="/privacy"
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:underline"
            >
              개인정보처리방침 보기
            </a>
          </div>
          {errors.privacyAgreed && (
            <p role="alert" className="pl-6 text-xs text-destructive-text">
              {errors.privacyAgreed.message}
            </p>
          )}
          <details className="group pl-6">
            <summary className={DETAIL_SUMMARY_TRIGGER_CLASSNAME}>
              <span className="group-open:hidden">자세히</span>
              <span className="hidden group-open:inline">접기</span>
              <ChevronDown
                aria-hidden
                className="size-3.5 motion-safe:transition-transform motion-safe:duration-200 group-open:rotate-180"
              />
            </summary>
            <div className={DETAIL_PANEL_CLASSNAME}>
              <dl className="flex flex-col gap-3">
                <div>
                  <dt className="font-semibold text-foreground">수집 항목</dt>
                  <dd className="mt-0.5 break-keep">
                    이메일, 비밀번호(해시하여 저장), 닉네임, 생년월일
                    <br />
                    구글 계정으로 가입하는 경우: 구글 계정 식별자, 이메일
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">이용 목적</dt>
                  <dd className="mt-0.5 break-keep">
                    회원가입 및 계정 관리, AI 캐릭터 대화·창작 등 서비스 제공, 신고 처리 및 콘텐츠
                    검토, 만 14세 미만 가입 제한, 약관 위반에 대한 제재 및 이의제기 처리, 서비스
                    보안 및 장애 대응
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">보유·이용기간</dt>
                  <dd className="mt-0.5 break-keep">
                    회원 탈퇴 시까지 보유하며 탈퇴 시 지체 없이 파기합니다. 다만 재가입 처리 및
                    남용 방지를 위해 이메일을 되돌릴 수 없는 값으로 변환하여 탈퇴일로부터 1년간
                    보관합니다.
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">동의를 거부할 권리</dt>
                  <dd className="mt-0.5 break-keep">
                    동의를 거부할 수 있으나, 위 항목은 서비스 제공에 필수적이므로 동의하지 않으면
                    회원가입이 제한됩니다.
                  </dd>
                </div>
              </dl>
              <p className="break-keep">
                서비스 이용 과정에서 자동으로 생성되는 정보(대화 내용, 창작 콘텐츠, 서버 접근 로그
                등)를 포함한 전체 내용은{" "}
                <a
                  href="/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-primary underline-offset-4 hover:underline focus-visible:underline"
                >
                  개인정보처리방침
                </a>
                에서 확인할 수 있습니다.
              </p>
            </div>
          </details>
        </div>

        <div className="flex flex-col gap-1">
          <Controller
            name="transferAgreed"
            control={control}
            render={({ field }) => (
              <label className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={field.value}
                  onCheckedChange={(checked) => field.onChange(checked === true)}
                  aria-invalid={!!errors.transferAgreed}
                />
                (필수) 개인정보 국외이전 동의
              </label>
            )}
          />
          {errors.transferAgreed && (
            <p role="alert" className="pl-6 text-xs text-destructive-text">
              {errors.transferAgreed.message}
            </p>
          )}
          <details className="group pl-6">
            <summary className={DETAIL_SUMMARY_TRIGGER_CLASSNAME}>
              <span className="group-open:hidden">자세히</span>
              <span className="hidden group-open:inline">접기</span>
              <ChevronDown
                aria-hidden
                className="size-3.5 motion-safe:transition-transform motion-safe:duration-200 group-open:rotate-180"
              />
            </summary>
            <div className={DETAIL_PANEL_CLASSNAME}>
              <dl className="flex flex-col gap-3">
                <div>
                  <dt className="font-semibold text-foreground">이전받는 자 / 연락처</dt>
                  <dd className="mt-0.5 break-keep">
                    · Google LLC — 1600 Amphitheatre Parkway, Mountain View, CA 94043, USA
                    <br />· Cloudflare, Inc. — 101 Townsend St., San Francisco, CA 94107, USA /
                    privacyquestions@cloudflare.com
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">이전되는 항목</dt>
                  <dd className="mt-0.5 break-keep">
                    · Google LLC: 대화 메시지 전문, 캐릭터·스토리 프롬프트, 발행 심사 시 업로드한
                    이미지
                    <br />· Cloudflare, Inc.: 이미지 생성 프롬프트와 생성 이미지, 업로드 파일,
                    데이터베이스 백업, 웹사이트 접속 시 통신 정보
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">이전 국가 / 시기 / 방법</dt>
                  <dd className="mt-0.5 break-keep">
                    미국. 대화 전송·이미지 생성·파일 업로드·웹사이트 접속 시점에 수시로, HTTPS 등
                    암호화된 통신으로 전송합니다. 데이터베이스 백업은 매일 정해진 시각에 전송합니다.
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">이용 목적 / 보유·이용기간</dt>
                  <dd className="mt-0.5 break-keep">
                    AI 응답 생성과 콘텐츠 자동 심사(Google LLC), 파일 저장·백업·웹사이트 전송
                    (Cloudflare, Inc.). 국내 원본이 삭제되면 재전송을 중단하며, 백업은 일간 7일·주간
                    4주 순환 보관합니다. 이전받는 자의 자체 보유기간은 각 사업자의 정책을 따릅니다.
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-foreground">동의를 거부할 권리와 거부의 효과</dt>
                  <dd className="mt-0.5 break-keep">
                    동의를 거부할 수 있습니다. 다만 위 이전은 AI 대화, 이미지 생성, 파일 저장,
                    웹사이트 전송 등 서비스의 핵심 기능 전반에 필요하므로, 동의하지 않으면 서비스를
                    이용할 수 없습니다. 가입 이후 동의를 철회하려는 경우 회원 탈퇴로 처리됩니다.
                  </dd>
                </div>
              </dl>
            </div>
          </details>
        </div>
      </div>
    </fieldset>
  );
}
