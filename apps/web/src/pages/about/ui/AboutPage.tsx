import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { CONTACT_EMAIL, SITE_NAME } from "@/shared/config/site";

import { ABOUT_SCREENSHOTS, type AboutScreenshot } from "../model/aboutScreenshots";

/** 문장 속 링크 — 저장소의 인라인 링크 관용구(`LegalConsentFields` 의 약관 링크)와 같다. 포커스는 밑줄로 준다. */
const INLINE_LINK_CLASSNAME =
  "whitespace-nowrap font-medium text-primary underline-offset-4 hover:underline focus-visible:underline";

const FEATURE_SECTIONS: { title: string; body: string; screenshot: AboutScreenshot }[] = [
  {
    title: "캐릭터와 대화해요",
    body: "행동과 대사를 적으면 캐릭터가 장면을 이어가고, 이야기에 맞는 그림이 함께 나오기도 해요.",
    screenshot: ABOUT_SCREENSHOTS.chatCharacter,
  },
  {
    title: "이야기 속 인물이 돼요",
    body: "스토리에서는 내가 주인공이에요. 내 선택에 따라 인물과의 관계나 상황이 달라지고, 그 결과가 엔딩을 바꿔요.",
    screenshot: ABOUT_SCREENSHOTS.storyPlay,
  },
  {
    title: "마음에 드는 작품을 골라요",
    body: "표지와 소개, 시작 상황을 보고 바로 시작할 수 있어요.",
    screenshot: ABOUT_SCREENSHOTS.contentDetail,
  },
  {
    title: "만난 장면을 모아요",
    body: "대화 중 만난 장면은 보관함에 모여요. 아직 못 본 장면은 흐리게 남아 다음 플레이를 기다려요.",
    screenshot: ABOUT_SCREENSHOTS.imageVault,
  },
  {
    title: "직접 만들어 나눠요",
    body: "캐릭터의 성격과 말투, 스토리의 시작 설정과 전개를 정하고, 이미지를 생성해 작품에 써요. 완성한 작품은 발행해 다른 사람과 나눠요.",
    screenshot: ABOUT_SCREENSHOTS.studioVault,
  },
  {
    title: "클로버",
    body: "무료 사용량을 다 쓰면 대화와 이미지 생성에 클로버가 쓰여요. 클로버는 출석체크와 미션으로 무료로 받을 수 있어요.",
    screenshot: ABOUT_SCREENSHOTS.cloverMissions,
  },
];

/** `/about` — 서비스 소개. 조회 없이 정해지는 정적 본문이라 로그인 여부와 무관하게 바로 그린다. */
export function AboutPage() {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-16 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-6">
        {/* h1은 헤더 메뉴·푸터의 링크 이름과 같은 "서비스 소개"로 두고, 화면의 첫 인상은 바로 아래 한 줄이 맡는다.
            그 한 줄이 web 화면에서 유일하게 페이지 제목 크기(1.5rem)를 넘는 글자다 — 처음 온 사람에게 서비스를 설명하는 이 화면에서만 허용한다. */}
        <div className="flex flex-col gap-2">
          <h1 className="text-sm font-semibold text-muted-foreground">서비스 소개</h1>
          <p className="break-keep text-balance text-4xl font-bold tracking-tight text-foreground">
            캐릭터와 이야기를 이어가는 곳
          </p>
        </div>
        <p className="break-keep text-sm text-foreground">
          {SITE_NAME}는 AI 캐릭터와 대화하고, 직접 만든 캐릭터와 스토리를 다른 사람과 나누는 서비스예요.
        </p>
        <Button asChild size="lg" className="self-start">
          <Link to="/">둘러보기</Link>
        </Button>
      </div>

      {FEATURE_SECTIONS.map((section, index) => (
        <FeatureSection key={section.title} {...section} isFirst={index === 0} />
      ))}

      <div className="flex flex-col gap-10">
        <AboutSection title="AI 생성물과 이용 연령">
          <p className="break-keep text-sm text-foreground">
            대화와 이미지는 생성형 AI가 만든 결과물이라 사실과 다르거나 부정확할 수 있어요. {SITE_NAME}는 만 14세
            이상이면 누구나 이용할 수 있어요.
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
      </div>
    </main>
  );
}

/**
 * 기능 하나 = 글 + 화면 캡처. DOM 순서는 언제나 글 → 그림이라 좁은 화면에서는 글을 먼저 읽고 그림이 따라온다.
 *
 * 두 열로 나누는 폭은 `md`(768px)다. `sm`(640px)에서 나누면 본문 폭 592px에서 그림 열(256px)과 간격(48px)을 빼고
 * 글 열이 288px — 16px 글자로 한 줄 18자 안팎 — 만 남는다. `md`에서는 384px(그림 열 288px)이 남고, 콘텐츠 그리드가
 * 이미 쓰는 브레이크포인트다. 그림은 매번 같은 오른쪽 — 글 열의 왼쪽 끝이 제목·소개문과 한 줄로 맞아 위에서 아래로 훑기 쉽다.
 */
function FeatureSection({
  title,
  body,
  screenshot,
  isFirst,
}: {
  title: string;
  body: string;
  screenshot: AboutScreenshot;
  isFirst: boolean;
}) {
  return (
    <section className="flex flex-col gap-6 md:flex-row md:items-center md:gap-12">
      <div className="flex flex-col gap-2 md:flex-1">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">{title}</h2>
        <p className="break-keep text-sm text-foreground">{body}</p>
      </div>
      <ScreenshotFrame screenshot={screenshot} isFirst={isFirst} />
    </section>
  );
}

/**
 * 폰 화면 캡처 틀. 폭을 고정하고 높이는 <img>의 width·height가 주는 비율로 정해져 그림이 오기 전에도 자리가 그대로다.
 * 폭 캡(256px, md 이상 288px)은 세로로 긴 폰 화면이 좁은 화면을 통째로 덮지 않게 하려는 것이다.
 * 캡처는 다크 테마라 라이트 배경 위에서는 어두운 사각형으로 서는데, 1px 보더가 그 가장자리를 의도된 틀로 읽히게 한다.
 *
 * 첫 캡처만 eager다 — 소개문 바로 아래라 스크롤 없이 보이는 범위에 틀의 윗부분이 걸리는 자리다. 나머지는 lazy.
 */
function ScreenshotFrame({ screenshot, isFirst }: { screenshot: AboutScreenshot; isFirst: boolean }) {
  return (
    <div className="w-64 shrink-0 self-center overflow-hidden rounded-xl border border-foreground/10 bg-muted md:w-72">
      <img
        src={screenshot.src}
        width={screenshot.width}
        height={screenshot.height}
        alt={screenshot.alt}
        loading={isFirst ? "eager" : "lazy"}
        decoding="async"
        className="block h-auto w-full"
      />
    </div>
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
