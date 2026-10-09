import { readAppShellHtml } from "./appShell";
import { injectHead } from "./html";
import { buildMetaTags, SITE_NAME } from "./meta";
import { resolvePublicOrigin } from "./origin";
import type { WorkerEnv } from "./workerRuntime";

/** 서비스 소개. 정적 경로 하나뿐이라 세그먼트 파싱이 필요 없다. */
export const ABOUT_PATH = "/about";

/** `src/shared/config/site.ts`의 `SITE_INTRO` 사본이다 — Worker는 별도 런타임이라 import하지 못한다. 함께 고친다. */
const ABOUT_INTRO = `${SITE_NAME}는 AI 캐릭터와 대화하고, 직접 만든 캐릭터와 스토리를 다른 사람과 나누는 서비스예요.`;

/**
 * `src/pages/about/ui/AboutPage.tsx`의 기능 소개 사본이다(제목·본문 문장만, 캡처는 해시된 번들 주소라 뺀다).
 * 문장이 페이지에 그대로 남아 있는지는 `aboutMeta.test.ts`가 소스를 읽어 확인한다.
 */
const ABOUT_FEATURES: { title: string; body: string }[] = [
  {
    title: "캐릭터와 대화해요",
    body: "행동과 대사를 적으면 캐릭터가 장면을 이어가고, 이야기에 맞는 그림이 함께 나오기도 해요.",
  },
  {
    title: "이야기 속 인물이 돼요",
    body: "스토리에서는 내가 주인공이에요. 내 선택에 따라 인물과의 관계나 상황이 달라지고, 그 결과가 엔딩을 바꿔요.",
  },
  {
    title: "마음에 드는 작품을 골라요",
    body: "표지와 소개, 시작 상황을 보고 바로 시작할 수 있어요.",
  },
  {
    title: "만난 장면을 모아요",
    body: "대화 중 만난 장면은 보관함에 모여요. 아직 못 본 장면은 흐리게 남아 다음 플레이를 기다려요.",
  },
  {
    title: "직접 만들어 나눠요",
    body: "캐릭터의 성격과 말투, 스토리의 시작 설정과 전개를 정하고, 이미지를 생성해 작품에 써요. 완성한 작품은 발행해 다른 사람과 나눠요.",
  },
  {
    title: "클로버",
    body: "무료 사용량 밖의 대화와 이미지 생성에는 클로버가 쓰여요. 클로버는 충전해서 쓰고, 미션 보상으로도 받을 수 있어요.",
  },
];

/** `src/shared/config/site.ts`의 `CONTACT_EMAIL` 사본이다. */
const CONTACT_EMAIL = "contact@ddona.site";

const EMPTY_ROOT = '<div id="root"></div>';

/**
 * 봇 <head>에 더할 조각을 만든다. 순수 함수다.
 *
 * 본문이 클라이언트 번들에 박힌 정적 문장이라 title·description·canonical 전부 조회 없이 정해진다 —
 * 홈·약관 메타와 같은 이유로 `API_BASE_URL` 가드보다 위에 둔다.
 */
export function buildAboutHead(origin: string): string {
  return buildMetaTags({
    title: `서비스 소개 — ${SITE_NAME}`,
    description: ABOUT_INTRO,
    canonical: `${origin}${ABOUT_PATH}`,
  });
}

/**
 * JS를 실행하지 않고 HTML만 읽는 검토 도구에 보일 소개 본문. 순수 함수이고 사용자 입력이 없어 이스케이프할 값이 없다.
 *
 * 화면은 React가 그린다 — `createRoot`가 첫 렌더에서 `#root`의 기존 자식을 지우므로 이 마크업은 번들이 뜨기 전까지만
 * 보인다. 그래서 스타일 없이 의미 구조(제목·문단·링크)만 둔다.
 */
export function buildAboutBody(): string {
  const features = ABOUT_FEATURES.map(
    ({ title, body }) => `<section><h2>${title}</h2><p>${body}</p></section>`,
  ).join("");

  return [
    "<main>",
    "<h1>서비스 소개</h1>",
    "<p>캐릭터와 이야기를 이어가는 곳</p>",
    `<p>${ABOUT_INTRO}</p>`,
    features,
    "<section><h2>AI 생성물과 이용 연령</h2>",
    `<p>대화와 이미지는 생성형 AI가 만든 결과물이라 사실과 다르거나 부정확할 수 있어요. ${SITE_NAME}는 만 14세 이상이면 누구나 이용할 수 있어요.</p></section>`,
    "<section><h2>문의</h2>",
    `<p>서비스 이용 중 궁금한 점은 <a href="mailto:${CONTACT_EMAIL}">${CONTACT_EMAIL}</a>로 메일을 보내 주세요.</p></section>`,
    '<nav><a href="/terms">이용약관</a> <a href="/privacy">개인정보처리방침</a></nav>',
    "</main>",
  ].join("");
}

/**
 * `/about` — UA를 가리지 않고 index.html에 title·description·canonical과 소개 본문을 넣어 응답한다.
 *
 * 다른 봇 분기와 달리 사람에게도 주는 이유: 회사 웹사이트를 확인하는 심사 도구가 알려진 크롤러 UA를 쓴다는 보장이
 * 없고, JS 없이 셸만 읽으면 본문이 비어 "제품 정보 없음"으로 판정된다. 본문이 React가 그리는 것과 같은 정적
 * 문장이라 사람이 받는 화면은 달라지지 않는다.
 */
export async function handleAboutMeta(
  request: Request,
  env: WorkerEnv,
): Promise<Response> {
  const html = await readAppShellHtml(request, env);
  const head = buildAboutHead(resolvePublicOrigin(env, request));
  // 빈 `#root`를 못 찾으면 본문 없이 head만 넣는다 — 넣을 자리를 모르는 채로 셸을 망가뜨리지 않는다.
  const withBody = html.replace(
    EMPTY_ROOT,
    () => `<div id="root">${buildAboutBody()}</div>`,
  );

  return new Response(injectHead(withBody, head), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
