import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// zod is big (about 30 KB gzipped) and only needed on the server, where Server Actions check their inputs.
// Components, and the lib modules they import, must never pull it into the browser: action input schemas
// live in server-only `*-schema.ts` files (lib/outcomes-schema.ts, lib/notify-schema.ts).
const ZOD_MESSAGE =
  "zod must not reach the browser. Put the schema in a server-only lib/*-schema.ts file and import it from the Server Action.";
const NO_ZOD_IN_THE_BROWSER = {
  paths: [{ name: "zod", message: ZOD_MESSAGE }],
  patterns: [
    { group: ["zod/*"], message: ZOD_MESSAGE },
    { group: ["@/lib/*-schema"], message: "Schemas are server-only. Import them from Server Actions, not from components." },
  ],
};

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["src/components/**/*.{ts,tsx}", "src/lib/outcomes.ts", "src/lib/notify.ts"],
    rules: {
      "no-restricted-imports": ["error", NO_ZOD_IN_THE_BROWSER],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
