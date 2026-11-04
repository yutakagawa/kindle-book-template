// 原稿チェック（npm run lint）と Node.js の要件のテスト。node --test で実行する。
//
// - docs/review-2026-11.md の 2: 辞書の誤検出で npm run lint:fix が原稿を壊す（「お客様に」→「お客ように」）
// - docs/review-2026-11.md の 4: Node.js の必要なバージョンが実際（Vivliostyle CLI は 22.12 以上）と合っていない
// - docs/review-2026-11.md の 7: 代替テキストの無い画像を警告する
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  compareVersions,
  minimumFromEngines,
  parseVersion,
  requiredNodeVersion,
  supportsEnvProxy
} from "../scripts/node-env.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const readJson = (p) => JSON.parse(read(p));

function havePandoc() {
  return spawnSync("pandoc", ["--version"]).status === 0;
}

// 一時ディレクトリに本を作る
function makeBook(chapterText, files = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kbt-lint-"));
  fs.mkdirSync(path.join(dir, "chapters"));
  fs.writeFileSync(path.join(dir, "book.yaml"), "title: テスト\nauthor: テスト\n");
  fs.writeFileSync(path.join(dir, "chapters", "01.md"), chapterText);
  for (const [name, data] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, name)), { recursive: true });
    fs.writeFileSync(path.join(dir, name), data);
  }
  return dir;
}

function runLint(args) {
  return spawnSync(process.execPath, [path.join(ROOT, "scripts", "check-manuscript.mjs"), ...args], {
    cwd: ROOT,
    encoding: "utf8",
    env: { ...process.env, NO_COLOR: "1", GITHUB_ACTIONS: "" }
  });
}

// ---------------------------------------------------------------------------
// 2. 表記ルールの辞書（prh）
// ---------------------------------------------------------------------------
describe("表記ルールの辞書（lint/dict）", () => {
  const prh = require("prh");
  const dicts = ["lint/dict/technical.yml", "lint/dict/project.yml"];

  // prh は辞書を読み込むときに各ルールの specs（from → to）を確かめ、合わなければ例外を投げる
  for (const dict of dicts) {
    test(`${dict} の specs がすべて通る`, () => {
      assert.doesNotThrow(() => prh.fromYAMLFilePath(path.join(ROOT, dict)));
    });
  }

  const engine = prh.fromYAMLFilePath(path.join(ROOT, "lint/dict/technical.yml"));
  const fix = (text) => engine.makeChangeSet("test.md", text).applyChangeSets(text);

  // 誤りではない表記（自動修正で壊してはいけない）
  const untouched = [
    "お客様にお届けします。",
    "田中様にご連絡ください。",
    "神様に祈ります。",
    "奥様によろしくお伝えください。",
    "皆様にお知らせします。",
    "お子様にも使えます。",
    "王様に会う。",
    "同様に書きます。",
    "多様に変化する。",
    "減少かどうかを調べます。",
    "多少かかります。",
    "希少かつ高価です。",
    "僅少ながら残っています。",
    "過少に見積もる。",
    "最少かどうか。",
    "手順に従って進めます。",
    "平等に扱う。",
    "出来上がりを確認します。"
  ];
  for (const text of untouched) {
    test(`「${text}」は変更しない`, () => assert.equal(fix(text), text));
  }

  // 直すべき表記
  const fixed = [
    ["次の様に書きます。", "次のように書きます。"],
    ["どの様に使うか。", "どのように使うか。"],
    ["数が少い。", "数が少ない。"],
    ["手順が少くなる。", "手順が少なくなる。"],
    ["処理を行なう。", "処理を行う。"]
  ];
  for (const [from, to] of fixed) {
    test(`「${from}」→「${to}」`, () => assert.equal(fix(from), to));
  }

  test("npm run lint:fix が「お客様に」「減少か」を書き換えない", () => {
    const original = "# テスト\n\nお客様にお届けします。減少かどうかを調べます。次の様に書きます。\n";
    const dir = makeBook(original);
    try {
      const r = runLint(["--only", "text", "--fix", dir]);
      const after = fs.readFileSync(path.join(dir, "chapters", "01.md"), "utf8");
      assert.match(after, /お客様にお届けします。/, r.stdout + r.stderr);
      assert.match(after, /減少かどうか/);
      assert.match(after, /次のように書きます。/, "本当の誤りは直すこと");
      assert.doesNotMatch(r.stdout, /様に => ように/);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// 4. Node.js のバージョン
// ---------------------------------------------------------------------------
describe("Node.js の要件", () => {
  const required = requiredNodeVersion();

  test("package.json の engines.node は >= の形式", () => {
    assert.ok(required, `engines.node を解釈できません: ${readJson("package.json").engines?.node}`);
  });

  test("engines.node は依存パッケージ（Vivliostyle CLI・textlint など）の要件以上", () => {
    const pkg = readJson("package.json");
    const checked = [];
    for (const name of Object.keys(pkg.devDependencies)) {
      const file = path.join(ROOT, "node_modules", name, "package.json");
      if (!fs.existsSync(file)) continue;
      const min = minimumFromEngines(JSON.parse(fs.readFileSync(file, "utf8")).engines?.node);
      if (!min) continue;
      checked.push(name);
      assert.ok(compareVersions(required, min) >= 0, `${name} は Node.js ${min} 以上が必要ですが、engines.node は ${required} です`);
    }
    assert.ok(checked.includes("@vivliostyle/cli"), "npm ci を実行してからテストしてください");
  });

  test("package-lock.json の engines が package.json と同じ", () => {
    assert.equal(readJson("package-lock.json").packages[""].engines?.node, readJson("package.json").engines.node);
  });

  test(".nvmrc のバージョンが engines.node を満たす", () => {
    const nvmrc = read(".nvmrc").trim();
    assert.ok(compareVersions(nvmrc, required) >= 0, `.nvmrc（${nvmrc}）が ${required} より古い`);
  });

  test("CI は .nvmrc の Node.js を使う", () => {
    for (const wf of fs.readdirSync(path.join(ROOT, ".github", "workflows"))) {
      const text = read(path.join(".github", "workflows", wf));
      if (!text.includes("actions/setup-node")) continue;
      assert.doesNotMatch(text, /node-version:\s*["']?\d/, `${wf} で Node.js のバージョンを直接書いています`);
      assert.match(text, /node-version-file:\s*\.nvmrc/, wf);
    }
  });

  test("ドキュメントに古い要件（Node.js 20 以上）が残っていない", () => {
    for (const doc of ["README.md", "docs/tutorial.md", "scripts/setup.sh"]) {
      // 「Node.js 20 以上」「[Node.js](https://nodejs.org/) 20 以上」など
      assert.doesNotMatch(read(doc), /Node(?:\.js)?(?:\]\([^)]*\))?\s*20(?:\.\d+)*\s*以上/, doc);
    }
  });

  test("scripts/setup.sh の MIN_NODE が engines.node と同じ", () => {
    assert.match(read("scripts/setup.sh"), new RegExp(`MIN_NODE="${required.replace(/\./g, "\\.")}"`));
  });

  test("parseVersion / compareVersions", () => {
    assert.deepEqual(parseVersion("v22.12.0"), [22, 12, 0]);
    assert.deepEqual(parseVersion("24"), [24, 0, 0]);
    assert.equal(compareVersions("v22.11.9", "22.12"), -1);
    assert.equal(compareVersions("22.12.0", "22.12"), 0);
    assert.equal(compareVersions("24.0.0", "22.12.0"), 1);
  });

  test("minimumFromEngines", () => {
    assert.equal(minimumFromEngines(">=22.12.0"), "22.12.0");
    assert.equal(minimumFromEngines(">= 20.18"), "20.18");
    assert.equal(minimumFromEngines("^20 || >=22"), null);
    assert.equal(minimumFromEngines(undefined), null);
  });

  test("NODE_USE_ENV_PROXY が使える Node.js の判定", () => {
    assert.equal(supportsEnvProxy("v20.19.0"), false);
    assert.equal(supportsEnvProxy("v22.12.0"), false);
    assert.equal(supportsEnvProxy("v22.21.0"), true);
    assert.equal(supportsEnvProxy("v23.11.0"), false);
    assert.equal(supportsEnvProxy("v24.0.0"), true);
  });
});

// ---------------------------------------------------------------------------
// 7. 代替テキストの無い画像
// ---------------------------------------------------------------------------
describe("代替テキストの確認", { skip: !havePandoc() && "pandoc が必要です" }, () => {
  // 1×1 の PNG
  const png = Buffer.from(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000" +
      "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082",
    "hex"
  );

  test("代替テキストの無い画像だけを警告する", () => {
    const dir = makeBook(
      "# テスト\n\n![](images/no-alt.png)\n\n![説明のある図](images/with-alt.png)\n\n![](images/attr-alt.png){alt=\"属性で書いた説明\"}\n",
      { "images/no-alt.png": png, "images/with-alt.png": png, "images/attr-alt.png": png }
    );
    try {
      const r = runLint(["--only", "links", dir]);
      const warnings = r.stdout.split("\n").filter((l) => l.includes("代替テキストがありません"));
      assert.equal(warnings.length, 1, r.stdout + r.stderr);
      assert.match(warnings[0], /no-alt\.png/);
      assert.equal(r.status, 0, "警告だけなら失敗にしない\n" + r.stdout);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
