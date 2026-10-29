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

  // 클로버 문구는 **두 사실을 함께** 말한다: 지금 막힌 이유
  // (클로버가 없다)와 다시 되는 시점(자정에 무료 한도가 돌아온다). 하나만 말하면 사용자가 할 수 있는
  // 일이 안 보인다. `retryAfterSeconds`는 KST 자정까지 남은 초라 참값이지만 최대 86400이라 초
  // 타이머를 걸지 않는다(day 창이 그랬던 것과 같은 이유).
  it("clover 창은 '클로버'와 '자정'을 둘 다 말하고 초는 쓰지 않는다", () => {
    const message = formatChatRateLimitMessage({ window: "clover", retryAfterSeconds: 43200 }, "chat", 43200);

    expect(message).toContain("클로버");
    expect(message).toContain("자정");
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

/** 상위 모델 방에는 무료분이 없다. 서버가 같은 `CLOVER_REQUIRED` 에 자정까지의 초를 실어 보내도 자정에 풀리지
 * 않으므로, 기본 모델 방의 "자정에 무료 한도" 문장을 내면 거짓이 된다 — 부족 사실만 말한다. */
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

  // 짝 테스트: 기본 모델 방은 여전히 자정을 말한다 — 위 케이스가 두 방의 문구를 하나로 합쳐 통과하지 못하게.
  it("기본 모델 방 문구와 다르다", () => {
    expect(formatChatRateLimitMessage(rateLimit, "premiumChat", 43200)).not.toBe(
      formatChatRateLimitMessage(rateLimit, "chat", 43200),
    );
  });

  it("분당 상한 문구는 기본 모델 방과 같다 — 모델과 무관한 상한이다", () => {
    const minute = { window: "minute", retryAfterSeconds: 30 } as const;

    expect(formatChatRateLimitMessage(minute, "premiumChat", 12)).toBe(formatChatRateLimitMessage(minute, "chat", 12));
  });
});

/** 상위 모델 미리보기도 상위 모델 방과 같이 무료분이 없다 — 기본 모델 미리보기 문구의 "자정에 무료 한도가 돌아와요"는
 * 거짓이 된다. 다만 미리보기 자리이므로 "채팅과 같은 한도"라는 사실은 먼저 말한다. */
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

  // 짝 테스트: 기본 모델 미리보기는 여전히 자정을 말한다.
  it("기본 모델 미리보기 문구와 다르다", () => {
    expect(formatChatRateLimitMessage(rateLimit, "preview", 43200)).toContain("자정");
    expect(formatChatRateLimitMessage(rateLimit, "premiumPreview", 43200)).not.toBe(
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

/** 출석판이 켜지면 무료 일일분이 없어 자정에 풀리는 것이 없다 — 네 자리 모두 자정 대신 출석판을 안내한다. 켜짐에서 기본·상위
 * 모델의 차이는 단가뿐이고 출석 클로버는 상위 모델에도 쓰여 문장을 가를 사실이 없다. */
describe("클로버 부족 문구 — 출석판", () => {
  const clover = { window: "clover", retryAfterSeconds: 43200 } as const;
  const SURFACES: ChatRateLimitSurface[] = ["chat", "premiumChat", "preview", "premiumPreview"];

  it.each(SURFACES)("켜져 있으면 %s 자리는 자정을 말하지 않고 출석판을 안내한다", (surface) => {
    const message = formatChatRateLimitMessage(clover, surface, 43200, true);
    expect(message).not.toContain("자정");
    expect(message).toContain("출석판");
  });

  it("켜져 있으면 채팅 두 자리는 같은 문장이다", () => {
    expect(formatChatRateLimitMessage(clover, "chat", 43200, true)).toBe("클로버가 부족해요 · 출석판에서 매일 받을 수 있어요");
    expect(formatChatRateLimitMessage(clover, "premiumChat", 43200, true)).toBe(
      "클로버가 부족해요 · 출석판에서 매일 받을 수 있어요",
    );
  });

  it("켜져 있으면 미리보기 두 자리는 미리보기 머리말 뒤에 같은 문장이다", () => {
    for (const surface of ["preview", "premiumPreview"] as const) {
      expect(formatChatRateLimitMessage(clover, surface, 43200, true)).toBe(
        "미리보기도 채팅과 같은 한도를 써요 · 클로버가 부족해요 · 출석판에서 매일 받을 수 있어요",
      );
    }
  });

  it("꺼져 있으면 네 자리 모두 지금 문장 그대로다", () => {
    expect(formatChatRateLimitMessage(clover, "chat", 43200, false)).toBe("클로버가 없어요 · 자정에 무료 한도가 돌아와요");
    expect(formatChatRateLimitMessage(clover, "premiumChat", 43200, false)).toBe("클로버가 부족해요");
    expect(formatChatRateLimitMessage(clover, "preview", 43200, false)).toBe(
      "미리보기도 채팅과 같은 한도를 써요 · 자정에 무료 한도가 돌아와요",
    );
    expect(formatChatRateLimitMessage(clover, "premiumPreview", 43200, false)).toBe(
      "미리보기도 채팅과 같은 한도를 써요 · 클로버가 부족해요",
    );
  });

  it.each(SURFACES)("읽어 주는 문장도 같은 문구다(%s, 켜짐)", (surface) => {
    expect(formatChatRateLimitAnnouncement(clover, surface, true)).toBe(formatChatRateLimitMessage(clover, surface, 43200, true));
  });

  it("분당 상한 문구는 출석판과 무관하다", () => {
    const minute = { window: "minute", retryAfterSeconds: 30 } as const;
    expect(formatChatRateLimitMessage(minute, "chat", 12, true)).toBe(formatChatRateLimitMessage(minute, "chat", 12, false));
    expect(formatChatRateLimitAnnouncement(minute, "preview", true)).toBe(formatChatRateLimitAnnouncement(minute, "preview", false));
  });
});

/** 배너 옆 이동 버튼. 미리보기 자리에는 두지 않는다 — 누르면 만들던 화면을 떠난다. */
describe("getRateLimitLinks", () => {
  const clover = { window: "clover", retryAfterSeconds: 43200 } as const;
  const minute = { window: "minute", retryAfterSeconds: 30 } as const;

  it("꺼져 있으면 채팅 방의 클로버 창에 클로버 채우기만 둔다", () => {
    expect(getRateLimitLinks(clover, "chat", false)).toEqual(["clover"]);
    expect(getRateLimitLinks(clover, "premiumChat", false)).toEqual(["clover"]);
  });

  it("켜져 있으면 채팅 방의 클로버 창에 클로버 채우기 뒤로 출석판을 둔다", () => {
    expect(getRateLimitLinks(clover, "chat", true)).toEqual(["clover", "attendance"]);
    expect(getRateLimitLinks(clover, "premiumChat", true)).toEqual(["clover", "attendance"]);
  });

  it.each([true, false])("미리보기 자리에는 버튼을 두지 않는다(켜짐 %s)", (attendanceEnabled) => {
    expect(getRateLimitLinks(clover, "preview", attendanceEnabled)).toEqual([]);
    expect(getRateLimitLinks(clover, "premiumPreview", attendanceEnabled)).toEqual([]);
  });

  it("분당 상한에는 버튼을 두지 않는다 — 기다리면 풀린다", () => {
    expect(getRateLimitLinks(minute, "chat", true)).toEqual([]);
    expect(getRateLimitLinks(minute, "premiumChat", true)).toEqual([]);
  });
});
