// @ts-check
import tseslint from "typescript-eslint";
import importX from "eslint-plugin-import-x";
import noRelativeImportPaths from "eslint-plugin-no-relative-import-paths";
import { createTypeScriptImportResolver } from "eslint-import-resolver-typescript";

/**
 * 이 저장소에는 린터가 존재한 적이 없다 — `turbo.json`의 `"lint": {}`는 빈 태스크였고 어느 패키지에도
 * `lint` 스크립트가 없어 `pnpm run lint`가 통과하는 것처럼 보이면서 아무것도 실행하지 않았다. 그래서
 * 컨벤션 위반이 408파일 중 119파일에 쌓였다(상대경로 158 · 타입단언 33 · interface Props 25).
 *
 * 규칙은 `hojeong-plugin-fe` 컨벤션 스킬의 rule-id에 대응시킨다 — 사람이 리뷰로 잡던 것을 기계로 옮기는
 * 것이 목적이라, **자동 검사가 가능한 것만** 넣는다. 렌더 단위 분리(COMP-07)처럼 판단이 필요한 규칙은
 * 서브에이전트 리뷰(`hojeong-architect`)의 몫으로 남긴다.
 */
export default tseslint.config(
  {
    // 생성물·빌드 산출물. `routeTree.gen.ts`는 TanStack Router가 만들고 `as XRouteImport` 단언이
    // 잔뜩 들어 있는데 손으로 고치면 다음 `vite build`가 되돌린다.
    ignores: [
      "**/dist/**",
      "**/node_modules/**",
      "**/.turbo/**",
      "**/.wrangler/**",
      "**/routeTree.gen.ts",
      "packages/api-types/src/generated.ts",
      // apps/api는 Python이다. `.venv` 안에 서드파티 `.js`(moto 템플릿 등)가 들어 있어
      // 그대로 두면 타입 정보 없는 파일에 타입 기반 규칙이 걸려 크래시한다.
      "apps/api/**",
    ],
  },

  // 타입 기반 규칙은 tsconfig가 아는 TS 파일에만 건다 — `.js`(설정·스크립트)에 걸면
  // "타입 정보가 없다"로 크래시한다.
  {
    files: ["**/*.{ts,tsx}"],
    extends: [...tseslint.configs.recommendedTypeChecked],
  },

  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "import-x": importX,
      "no-relative-import-paths": noRelativeImportPaths,
    },
    settings: {
      // `import-x`의 경로 규칙(`no-cycle`·`no-restricted-paths`)은 resolver 없이는 못 돈다 —
      // 기본 node resolver는 v4에서 인터페이스가 바뀌어 크래시한다. 워크스페이스가 여러 tsconfig로
      // 갈려 있으므로 전부 넘겨 `@/` alias와 `@ai-character-chat/*` 패키지 참조를 함께 풀게 한다.
      "import-x/resolver-next": [
        createTypeScriptImportResolver({
          project: [
            "apps/web/tsconfig.json",
            "apps/admin/tsconfig.json",
            "packages/ui/tsconfig.json",
            "packages/api-types/tsconfig.json",
          ],
        }),
      ],
    },
    rules: {
      // TS-01 · any 금지
      "@typescript-eslint/no-explicit-any": "error",
      // TS-02 · non-null assertion 금지
      "@typescript-eslint/no-non-null-assertion": "error",
      // TS-03 · as 단언 최소화. `as const`와 `as unknown`은 규칙이 명시적으로 허용한다.
      "@typescript-eslint/consistent-type-assertions": [
        "error",
        { assertionStyle: "never" },
      ],
      // TS-06 · type 우선, interface는 확장·선언병합이 필요할 때만 (--fix 가능)
      "@typescript-eslint/consistent-type-definitions": ["error", "type"],
      // IMP-03 · import type 분리 (--fix 가능)
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      // IMP-04 · 순환 import 금지
      "import-x/no-cycle": ["error", { maxDepth: Infinity }],
      // COMP-04 · JSX 중첩 삼항 금지 (early return 또는 컴포넌트 분리로)
      "no-nested-ternary": "error",
    },
  },

  // IMP-01 · path alias. `@/`가 정의된 앱에만 건다 — `packages/ui`는 컴포넌트가 한 폴더에 평평하게
  // 있어 2단계 이상 상위 경로가 애초에 0건이고 alias를 도입할 이유가 없다.
  //
  // `rootDir`는 플러그인이 `path.join(context.getCwd(), rootDir)`로 쓰므로 **저장소 루트 기준**이다
  // (`"src"`로 두면 `<repo>/src`를 찾다가 조용히 0건을 낸다 — 처음에 그렇게 넣고 158곳이 0으로
  // 나오는 걸 보고 알았다). 앱마다 루트가 다르니 블록을 나눈다.
  //
  // `allowedDepth: 1`은 저장소 규약(`apps/web/CLAUDE.md`)이 **레이어를 넘는** import에만 alias를
  // 요구하기 때문이다. 슬라이스 내부 `../model/x`는 그대로 두고 `@/` 그룹과 빈 줄로 가른다는 것이
  // 기존 관례다 — 이 옵션 없이는 그 112곳까지 잡아 관례와 싸운다.
  {
    files: ["apps/web/src/**/*.{ts,tsx}"],
    rules: {
      "no-relative-import-paths/no-relative-import-paths": [
        "error",
        { allowSameFolder: true, allowedDepth: 1, rootDir: "apps/web/src", prefix: "@" },
      ],
    },
  },
  {
    files: ["apps/admin/src/**/*.{ts,tsx}"],
    rules: {
      "no-relative-import-paths/no-relative-import-paths": [
        "error",
        { allowSameFolder: true, allowedDepth: 1, rootDir: "apps/admin/src", prefix: "@" },
      ],
    },
  },

  {
    // FSD-02 · 레이어 의존은 상위→하위 단방향. 서열은 app → pages → widgets → features → entities → shared.
    // `routes/`는 TanStack Router가 강제하는 위치라 FSD 레이어가 아니며 pages와 같은 높이로 다룬다.
    //
    // **한계: 이 규칙은 정적 `import` 문만 본다.** `validateSearchFallback.test.ts`가 shared에서
    // `import.meta.glob("../../../routes/*.tsx")`로 상위 레이어를 읽는 역참조는 잡지 못한다(도입 직후
    // 0건이 나와 확인했다 — 그 파일은 실제로 위반인데도 통과한다). 글롭·동적 import로 레이어를 넘는
    // 것은 여전히 사람이나 `hojeong-architect` 리뷰의 몫이다.
    files: ["apps/web/src/**/*.{ts,tsx}"],
    rules: {
      "import-x/no-restricted-paths": [
        "error",
        {
          zones: [
            { target: "./apps/web/src/shared", from: "./apps/web/src/entities" },
            { target: "./apps/web/src/shared", from: "./apps/web/src/features" },
            { target: "./apps/web/src/shared", from: "./apps/web/src/widgets" },
            { target: "./apps/web/src/shared", from: "./apps/web/src/pages" },
            { target: "./apps/web/src/shared", from: "./apps/web/src/routes" },
            { target: "./apps/web/src/shared", from: "./apps/web/src/app" },

            { target: "./apps/web/src/entities", from: "./apps/web/src/features" },
            { target: "./apps/web/src/entities", from: "./apps/web/src/widgets" },
            { target: "./apps/web/src/entities", from: "./apps/web/src/pages" },
            { target: "./apps/web/src/entities", from: "./apps/web/src/routes" },
            { target: "./apps/web/src/entities", from: "./apps/web/src/app" },

            { target: "./apps/web/src/features", from: "./apps/web/src/widgets" },
            { target: "./apps/web/src/features", from: "./apps/web/src/pages" },
            { target: "./apps/web/src/features", from: "./apps/web/src/routes" },
            { target: "./apps/web/src/features", from: "./apps/web/src/app" },

            { target: "./apps/web/src/widgets", from: "./apps/web/src/pages" },
            { target: "./apps/web/src/widgets", from: "./apps/web/src/routes" },
            { target: "./apps/web/src/widgets", from: "./apps/web/src/app" },
          ],
        },
      ],
    },
  },

  {
    // 테스트는 픽스처를 최상위에 두는 관례가 있고(`filterShortcuts.test.ts`가 main의 선례),
    // 타입 단언으로 부분 객체를 만드는 것이 본문 코드보다 정당하다.
    files: ["**/*.test.{ts,tsx}"],
    rules: {
      "@typescript-eslint/consistent-type-assertions": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
    },
  },
);
