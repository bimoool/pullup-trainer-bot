import { defineConfig } from "vitest/config";

// issue #306: vitest гоняет только общие JSON-векторы Live Engine v2 (contracts/live_engine_vectors.json) —
// те же, что pytest. Остальные юнит-тесты по-прежнему на node --test (npm run test:unit).
export default defineConfig({
  test: {
    include: ["tests/**/*.vitest.ts"],
    environment: "node",
  },
});
