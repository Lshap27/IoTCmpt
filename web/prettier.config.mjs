/** @type {import("prettier").Config} */
const config = {
  printWidth: 110,
  // The team develops on Windows and CI runs on Linux; do not fail checks only
  // because Git materialized a file with the platform's line ending.
  endOfLine: "auto",
};

export default config;
