import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { CONTACT_EMAIL, SITE_INTRO } from "@/shared/config/site";

/** 문장 속 링크 — 저장소의 인라인 링크 관용구(`LegalConsentFields` 의 약관 링크)와 같다. 포커스는 밑줄로 준다. */
const INLINE_LINK_CLASSNAME =
  "whitespace-nowrap font-medium text-primary underline-offset-4 hover:underline focus-visible:underline";

/** `/about` — 서비스 소개. 조회 없이 정해지는 정적 본문이라 로그인 여부와 무관하게 바로 그린다. */
export function AboutPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">서비스 소개</h1>
      <p className="break-keep text-sm text-foreground">{SITE_INTRO}</p>

      <AboutSection title="할 수 있는 것">
        <ul className="flex list-disc flex-col gap-1.5 pl-5 break-keep text-sm text-foreground marker:text-muted-foreground">
          <li>대화 — 창작자들이 만든 캐릭터와 이야기하거나, 스토리 속 인물이 되어 장면을 이어가요.</li>
          <li>창작 — 캐릭터의 성격·말투·배경과 스토리의 시작 설정·전개를 직접 만들어 발행해요.</li>
          <li>이미지 — 캐릭터와 장면 이미지를 생성해 작품에 써요.</li>
        </ul>
      </AboutSection>

      <AboutSection title="AI 생성물 안내">
        <p className="break-keep text-sm text-foreground">
          대화와 이미지는 생성형 AI가 자동으로 만든 결과물로, 사실이 아니거나 부정확할 수 있어요.
        </p>
      </AboutSection>

      <AboutSection title="문의">
        <p className="break-keep text-sm text-foreground">
          서비스 이용 중 궁금한 점은{" "}
          <a href={`mailto:${CONTACT_EMAIL}`} className={INLINE_LINK_CLASSNAME}>
            {CONTACT_EMAIL}
          </a>
          로 메일을 보내거나{" "}
          <Link to="/inquiries/new" className={INLINE_LINK_CLASSNAME}>
            문의하기
          </Link>{" "}
          페이지에서 남겨 주세요.
        </p>
      </AboutSection>
    </main>
  );
}

function AboutSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xl font-semibold tracking-tight text-foreground">{title}</h2>
      {children}
    </section>
  );
}
