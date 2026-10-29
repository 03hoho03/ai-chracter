import { describe, expect, it } from "vitest";

import {
  formatChatRateLimitAnnouncement,
  formatChatRateLimitMessage,
  getChatRateLimit,
  getRateLimitLinks,
  type ChatRateLimitSurface,
} from "./chatRateLimit";

describe("getChatRateLimit", () => {
  it.each(["minute", "clover"] as const)("채팅 창(%s)은 좁혀진 값으로 돌려준다", (window) => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: window === "clover" ? "CLOVER_REQUIRED" : "USER_LIMIT", retryAfterSeconds: 7, window },
        message: "x",
      }),
    ).toEqual({ window, retryAfterSeconds: 7 });
  });

  it("이미지 창은 undefined다 — 채팅 배너는 minute/clover 두 문구만 갖는다", () => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "USER_LIMIT", retryAfterSeconds: 7, window: "image" },
        message: "x",
      }),
    ).toBeUndefined();
  });

  // auth 창도 undefined다. 이 케이스는 런타임 신호가 아니라
  // 타입 신호였다: `getChatRateLimit`이 배제 목록(`window === "image"`만 걸러 undefined)이던 동안은
  // `window` enum에 `"auth"`를 더하는 순간 `ChatRateLimit["window"]`에 안 들어가 *컴파일이 안 됐다*
  // (단언 실패가 아니라 타입 에러). 허용 목록으로 뒤집은 지금은 평범한 런타임 단언으로 통과한다.
  it("auth 창도 undefined다 — 배제 목록이던 동안은 이 케이스가 타입 에러였다", () => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "AUTH_LIMIT", retryAfterSeconds: 3540, window: "auth" },
        message: "x",
      }),
    ).toBeUndefined();
  });

  // BE가 더 이상 `window: "day"`를 보내지 않으므로(무료 일일분을
  // 넘으면 클로버를 쓰거나 `CLOVER_REQUIRED`가 나간다, `rate_limit_gate.py`에 `"day"` 리터럴 0건)
  // 채팅 투영의 허용 목록에서 뺐다. 🔴 이 자리는 `assertNever`가 잡아 주지 않는다 — 허용 목록은
  // 그냥 `if`라, 빼는 것을 잊었어도 컴파일은 통과한다. 그래서 런타임 단언으로 고정한다.
  it("day 창은 undefined다 — BE가 더 이상 보내지 않아 허용 목록에서 뺐다", () => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "USER_LIMIT", retryAfterSeconds: 86400, window: "day" },
        message: "x",
      }),
    ).toBeUndefined();
  });
});

describe("formatChatRateLimitMessage", () => {
  it("minute 창은 남은 초를 문구에 넣는다 — 배너의 카운트다운이 이 값을 매초 새로 준다", () => {
    const message = formatChatRateLimitMessage({ window: "minute", retryAfterSeconds: 30 }, "chat", 12);

    expect(message).toContain("12초");
    expect(message).toContain("너무 빠르게");
  });

  // 무료 일일분이 없어 자정에 풀리는 것이 없다. 클로버 문구는 막힌 이유(클로버가 부족하다)와 클로버를 다시 얻는
  // 무료 길(출석판)을 함께 말한다. 서버가 싣는 `retryAfterSeconds` 는 다시 보낼 수 있는 시점이 아니라 초를 쓰지 않는다.
  it("clover 창은 클로버 부족과 출석판을 말하고 자정·초는 쓰지 않는다", () => {
    const message = formatChatRateLimitMessage({ window: "clover", retryAfterSeconds: 43200 }, "chat", 43200);

    expect(message).toContain("클로버가 부족해요");
    expect(message).toContain("출석판");
    expect(message).not.toContain("자정");
    expect(message).not.toContain("초");
  });

  it.each(["minute", "clover"] as const)("미리보기는 같은 한도를 쓴다고 먼저 말한다(%s)", (window) => {
    const message = formatChatRateLimitMessage({ window, retryAfterSeconds: 30 }, "preview", 30);

    expect(message).toContain("미리보기도 채팅과 같은 한도를 써요");
  });

  it("같은 창이어도 채팅과 미리보기 문구가 다르다", () => {
    const rateLimit = { window: "minute", retryAfterSeconds: 30 } as const;

    expect(formatChatRateLimitMessage(rateLimit, "chat", 30)).not.toBe(
      formatChatRateLimitMessage(rateLimit, "preview", 30),
    );
  });

  // 0초에서 "0초 뒤 다시"가 남으면 안 된다.
  // 카운트다운이 끝나도 버튼은 aria-disabled=false로 풀려 클릭이 통과하므로 문구도 그 사실을
  // 말해야 한다.
  it("minute 창은 0초에서 카운트다운 대신 즉시 재전송 문구를 쓴다(chat)", () => {
    const message = formatChatRateLimitMessage({ window: "minute", retryAfterSeconds: 30 }, "chat", 0);

    expect(message).not.toContain("0초");
    expect(message).toContain("다시 보낼 수 있어요");
  });

  it("minute 창은 0초에서도 미리보기 리드를 먼저 말한다(preview)", () => {
    const message = formatChatRateLimitMessage({ window: "minute", retryAfterSeconds: 30 }, "preview", 0);

    expect(message).not.toContain("0초");
    expect(message).toContain("다시 보낼 수 있어요");
    expect(message).toContain("미리보기도 채팅과 같은 한도를 써요");
  });
});

describe("formatChatRateLimitAnnouncement", () => {
  // secondsLeft를 받지 않아 마운트 1회 말고는
  // 뮤테이션이 원리적으로 불가능하다. 숫자가 전혀 없어야 role="alert"가 매초 재발화하지 않는다.
  it("minute 창은 초 숫자 없이 대기 안내만 말한다 — 매초 재발화를 막는 설계다", () => {
    const message = formatChatRateLimitAnnouncement({ window: "minute", retryAfterSeconds: 30 }, "chat");

    expect(message).not.toMatch(/\d/);
    expect(message).toContain("잠시 뒤");
  });

  it("clover 창 문구는 formatChatRateLimitMessage와 동일하다 — 사본이 아니다", () => {
    const rateLimit = { window: "clover", retryAfterSeconds: 43200 } as const;

    expect(formatChatRateLimitAnnouncement(rateLimit, "chat")).toBe(
      formatChatRateLimitMessage(rateLimit, "chat", 43200),
    );
  });
});

/** 🔴 확인 429는 `window: "clover"`로 오지만 **배너가 아니다.**
 * 이 줄이 없으면 동의를 물어야 할 상황에 "클로버가 없어요"라는 틀린 배너가 뜬다 — 잔액은
 * 충분한데(BE는 모자라면 아예 묻지 않는다). 허용 목록은 `assertNever`가 안 잡는 자리라
 * 런타임 단언이 유일한 방어다. */
describe("getChatRateLimit — 확인 코드", () => {
  it("CLOVER_CONFIRM_REQUIRED는 배너로 새지 않는다", () => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "CLOVER_CONFIRM_REQUIRED", retryAfterSeconds: 3600, window: "clover" },
        message: "x",
      }),
    ).toBeUndefined();
  });

  it("부족(CLOVER_REQUIRED)은 그대로 배너로 간다 — 짝 테스트", () => {
    expect(
      getChatRateLimit({
        status: 429,
        detail: { code: "CLOVER_REQUIRED", retryAfterSeconds: 3600, window: "clover" },
        message: "x",
      }),
    ).toEqual({ window: "clover", retryAfterSeconds: 3600 });
  });
});

/** 상위 모델 방에도 무료분이 없다. 서버가 같은 `CLOVER_REQUIRED` 에 자정까지의 초를 실어 보내도 자정에 풀리지
 * 않는다 — 자정이나 무료 한도를 약속하지 않는다. */
describe("상위 모델 방의 클로버 부족 문구", () => {
  const rateLimit = { window: "clover", retryAfterSeconds: 43200 } as const;

  it("부족 사실만 말하고 자정·무료 한도를 약속하지 않는다", () => {
    const message = formatChatRateLimitMessage(rateLimit, "premiumChat", 43200);

    expect(message).toContain("클로버가 부족해요");
    expect(message).not.toContain("자정");
    expect(message).not.toContain("무료");
  });

  it("읽어 주는 문장도 같은 문구다 — 사본이 아니다", () => {
    expect(formatChatRateLimitAnnouncement(rateLimit, "premiumChat")).toBe(
      formatChatRateLimitMessage(rateLimit, "premiumChat", 43200),
    );
  });

  // 기본·상위 모델의 차이는 단가뿐이고 출석 클로버는 상위 모델에도 쓰여 두 방의 문장을 가를 사실이 없다.
  it("기본 모델 방 문구와 같다", () => {
    expect(formatChatRateLimitMessage(rateLimit, "premiumChat", 43200)).toBe(
      formatChatRateLimitMessage(rateLimit, "chat", 43200),
    );
  });

  it("분당 상한 문구는 기본 모델 방과 같다 — 모델과 무관한 상한이다", () => {
    const minute = { window: "minute", retryAfterSeconds: 30 } as const;

    expect(formatChatRateLimitMessage(minute, "premiumChat", 12)).toBe(formatChatRateLimitMessage(minute, "chat", 12));
  });
});

/** 상위 모델 미리보기도 무료분이 없어 자정을 약속하지 않는다. 미리보기 자리이므로 "채팅과 같은 한도"라는 사실은 먼저 말한다. */
describe("상위 모델 미리보기의 클로버 부족 문구", () => {
  const rateLimit = { window: "clover", retryAfterSeconds: 43200 } as const;

  it("부족 사실을 말하고 자정·무료 한도를 약속하지 않는다", () => {
    const message = formatChatRateLimitMessage(rateLimit, "premiumPreview", 43200);

    expect(message).toContain("부족");
    expect(message).not.toContain("자정");
    expect(message).not.toContain("무료");
  });

  it("미리보기 머리말을 먼저 말한다", () => {
    expect(formatChatRateLimitMessage(rateLimit, "premiumPreview", 43200)).toMatch(/^미리보기도 채팅과 같은 한도를 써요/);
  });

  it("읽어 주는 문장도 같은 문구다", () => {
    expect(formatChatRateLimitAnnouncement(rateLimit, "premiumPreview")).toBe(
      formatChatRateLimitMessage(rateLimit, "premiumPreview", 43200),
    );
  });

  // 상위 모델 방과 같은 이유로 기본 모델 미리보기와 가를 사실이 없다.
  it("기본 모델 미리보기 문구와 같다", () => {
    expect(formatChatRateLimitMessage(rateLimit, "preview", 43200)).not.toContain("자정");
    expect(formatChatRateLimitMessage(rateLimit, "premiumPreview", 43200)).toBe(
      formatChatRateLimitMessage(rateLimit, "preview", 43200),
    );
  });

  it("분당 상한 문구와 안내 문장은 기본 모델 미리보기와 같다", () => {
    const minute = { window: "minute", retryAfterSeconds: 30 } as const;

    expect(formatChatRateLimitMessage(minute, "premiumPreview", 12)).toBe(formatChatRateLimitMessage(minute, "preview", 12));
    expect(formatChatRateLimitMessage(minute, "premiumPreview", 0)).toBe(formatChatRateLimitMessage(minute, "preview", 0));
    expect(formatChatRateLimitAnnouncement(minute, "premiumPreview")).toBe(formatChatRateLimitAnnouncement(minute, "preview"));
  });
});

/** 무료 일일분이 없어 자정에 풀리는 것이 없다 — 네 자리 모두 자정 대신 출석판을 안내한다. 기본·상위 모델의 차이는
 * 단가뿐이고 출석 클로버는 상위 모델에도 쓰여 문장을 가를 사실이 없다. 출석판 스위치를 읽지 않고도 이 문장이어야 한다. */
describe("클로버 부족 문구 — 출석판", () => {
  const clover = { window: "clover", retryAfterSeconds: 43200 } as const;
  const SURFACES: ChatRateLimitSurface[] = ["chat", "premiumChat", "preview", "premiumPreview"];

  it.each(SURFACES)("%s 자리는 자정·무료 한도를 말하지 않고 출석판을 안내한다", (surface) => {
    const message = formatChatRateLimitMessage(clover, surface, 43200);
    expect(message).not.toContain("자정");
    expect(message).not.toContain("무료");
    expect(message).toContain("출석판");
  });

  it("채팅 두 자리는 같은 문장이다", () => {
    expect(formatChatRateLimitMessage(clover, "chat", 43200)).toBe("클로버가 부족해요 · 출석판에서 매일 받을 수 있어요");
    expect(formatChatRateLimitMessage(clover, "premiumChat", 43200)).toBe("클로버가 부족해요 · 출석판에서 매일 받을 수 있어요");
  });

  it("미리보기 두 자리는 미리보기 머리말 뒤에 같은 문장이다", () => {
    for (const surface of ["preview", "premiumPreview"] as const) {
      expect(formatChatRateLimitMessage(clover, surface, 43200)).toBe(
        "미리보기도 채팅과 같은 한도를 써요 · 클로버가 부족해요 · 출석판에서 매일 받을 수 있어요",
      );
    }
  });

  it.each(SURFACES)("읽어 주는 문장도 같은 문구다(%s)", (surface) => {
    expect(formatChatRateLimitAnnouncement(clover, surface)).toBe(formatChatRateLimitMessage(clover, surface, 43200));
  });
});

/** 배너 옆 이동 버튼. 미리보기 자리에는 두지 않는다 — 누르면 만들던 화면을 떠난다. */
describe("getRateLimitLinks", () => {
  const clover = { window: "clover", retryAfterSeconds: 43200 } as const;
  const minute = { window: "minute", retryAfterSeconds: 30 } as const;

  // 문구가 출석판을 말하므로 바로 갈 길을 함께 둔다. 출석판 스위치를 읽지 않고도 늘 둔다.
  it("채팅 방의 클로버 창에 클로버 채우기 뒤로 출석판을 둔다", () => {
    expect(getRateLimitLinks(clover, "chat")).toEqual(["clover", "attendance"]);
    expect(getRateLimitLinks(clover, "premiumChat")).toEqual(["clover", "attendance"]);
  });

  it("미리보기 자리에는 버튼을 두지 않는다", () => {
    expect(getRateLimitLinks(clover, "preview")).toEqual([]);
    expect(getRateLimitLinks(clover, "premiumPreview")).toEqual([]);
  });

  it("분당 상한에는 버튼을 두지 않는다 — 기다리면 풀린다", () => {
    expect(getRateLimitLinks(minute, "chat")).toEqual([]);
    expect(getRateLimitLinks(minute, "premiumChat")).toEqual([]);
  });
});
