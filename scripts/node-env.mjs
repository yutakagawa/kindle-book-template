// Node.js のバージョンの確認（scripts/check-manuscript.mjs とテストから使う）
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// "v22.12.0" / "22.12" → [22, 12, 0]
export function parseVersion(v) {
  const m = String(v).match(/(\d+)(?:\.(\d+))?(?:\.(\d+))?/);
  if (!m) throw new Error(`バージョンを解釈できません: ${v}`);
  return [Number(m[1]), Number(m[2] ?? 0), Number(m[3] ?? 0)];
}

export function compareVersions(a, b) {
  const [x, y] = [parseVersion(a), parseVersion(b)];
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
  return 0;
}

// engines の ">=22.12.0" から最小バージョンを取り出す（">=" 以外の書き方は扱わない）
export function minimumFromEngines(range) {
  const m = String(range ?? "").trim().match(/^>=\s*v?(\d+(?:\.\d+){0,2})$/);
  return m ? m[1] : null;
}

// package.json の engines.node に書いた最小バージョン
export function requiredNodeVersion(root = ROOT) {
  const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  return minimumFromEngines(pkg.engines?.node);
}

// NODE_USE_ENV_PROXY（fetch が HTTPS_PROXY を使う）が使える Node.js か: v24.0.0 以降と v22.21.0 以降の 22 系
export function supportsEnvProxy(version = process.version) {
  const [major] = parseVersion(version);
  if (major >= 24) return true;
  return major === 22 && compareVersions(version, "22.21.0") >= 0;
}
