// ESLint v9 flat config — 最小规则集
// 目标：捕获基础错误（未声明变量、未用变量、宽松等号），不强求风格
import globals from "globals";

export default [
  {
    files: ["static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      globals: {
        ...globals.browser,
        // 项目特有：Alpine 由 vendor script 全局注入；window.__delMsg 内部桥
        Alpine: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrors: "none",
        },
      ],
      eqeqeq: ["error", "always", { null: "ignore" }],
      "no-console": ["warn", { allow: ["warn", "error"] }],
      "no-var": "error",
      "prefer-const": "warn",
    },
  },
  {
    // vendor 文件不参与 lint
    ignores: ["static/vendor/**", "node_modules/**"],
  },
];
