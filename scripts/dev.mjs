import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const backendDir = join(rootDir, "backend");
const frontendDir = join(rootDir, "frontend");
const pythonBin = join(backendDir, ".venv", "bin", "python");
const frontendModules = join(frontendDir, "node_modules");
const backendEnv = join(backendDir, ".env");
const frontendEnv = join(frontendDir, ".env");

function fail(message) {
  console.error(`\n${message}\n`);
  process.exit(1);
}

function ensureReady() {
  if (!existsSync(pythonBin)) {
    fail(
      "后端虚拟环境不存在。请先运行：cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt",
    );
  }
  if (!existsSync(frontendModules)) {
    fail("前端依赖不存在。请先运行：cd frontend && npm install");
  }
  if (!existsSync(backendEnv)) {
    fail("缺少 backend/.env。请先运行：cp backend/.env.example backend/.env，并填入 MISTRAL_API_KEY");
  }
  if (!existsSync(frontendEnv)) {
    fail("缺少 frontend/.env。请先运行：cp frontend/.env.example frontend/.env");
  }
}

function startProcess(name, command, args, cwd) {
  const child = spawn(command, args, {
    cwd,
    stdio: ["ignore", "pipe", "pipe"],
    env: process.env,
  });

  child.stdout.on("data", (chunk) => {
    process.stdout.write(`[${name}] ${chunk}`);
  });
  child.stderr.on("data", (chunk) => {
    process.stderr.write(`[${name}] ${chunk}`);
  });
  child.on("exit", (code, signal) => {
    if (!shuttingDown) {
      console.log(`[${name}] 已退出 code=${code ?? "null"} signal=${signal ?? "null"}`);
      shutdown();
    }
  });
  return child;
}

let shuttingDown = false;
const children = [];

function shutdown() {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) {
      child.kill("SIGINT");
    }
  }
}

ensureReady();

children.push(
  startProcess(
    "backend",
    pythonBin,
    ["-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"],
    backendDir,
  ),
);

children.push(
  startProcess("frontend", "npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], frontendDir),
);

console.log("Vox Bridge 开发服务已启动：");
console.log("- 前端：http://127.0.0.1:5173");
console.log("- 后端：http://127.0.0.1:8000");
console.log("按 Ctrl+C 同时停止前后端。");

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
