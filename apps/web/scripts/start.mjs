import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const nextBin = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));
const hostname = process.env.WEB_HOST || "0.0.0.0";
const port = process.env.PORT || process.env.WEB_PORT || "3000";
const passthroughArgs = process.argv.slice(2);
const hasOption = (names) =>
  passthroughArgs.some((arg) => names.some((name) => arg === name || arg.startsWith(`${name}=`)));
const nextArgs = ["start", ...passthroughArgs];

if (!hasOption(["--hostname", "-H"])) {
  nextArgs.push("--hostname", hostname);
}

if (!hasOption(["--port", "-p"])) {
  nextArgs.push("--port", port);
}

const child = spawn(
  process.execPath,
  [nextBin, ...nextArgs],
  {
    env: process.env,
    stdio: "inherit",
  },
);

const forwardSignal = (signal) => {
  if (!child.killed) {
    child.kill(signal);
  }
};

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
