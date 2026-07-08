import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../server/openapi.json",
  output: {
    path: "src/lib/api-client",
    format: "prettier",
  },
  plugins: ["@hey-api/client-fetch", "@hey-api/typescript", "@hey-api/sdk"],
});
