import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

export default [
  ...compat.config({ extends: ["next/core-web-vitals"] }),
  { ignores: ["node_modules/**", ".next/**"] },
];
