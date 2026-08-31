import { FlatCompat } from "@eslint/eslintrc";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const compat = new FlatCompat({ baseDirectory: directory });

const config = [
  {
    ignores: [
      ".next*/**",
      ".open-next/**",
      ".sites-build/**",
      "dist/**",
      "next-env.d.ts",
      "public/downloads/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // Protected evidence, remote platform media, and tiny official logos are
      // intentionally streamed by their existing URLs instead of Next's image proxy.
      "@next/next/no-img-element": "off",
    },
  },
];

export default config;
