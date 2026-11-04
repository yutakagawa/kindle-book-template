// scripts/check-manuscript.mjs（原稿の品質チェック）のテスト。
//
// 実行: node --test tests/   （先に npm ci。リンクのチェックには pandoc が必要）
//
// 一時ディレクトリに小さな本を作り、コマンドとして実行して終了コードと出力を確かめる。
import { spawnSync, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { after, before, describe, test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SCRIPT = path.join(ROOT, "scripts", "check-manuscript.mjs");
const PANDOC = process.env.PANDOC || "pandoc";
const hasPandoc = !spawnSync(PANDOC, ["--version"]).error;
const hasNodeModules = fs.existsSync(path.join(ROOT, "node_modules", "textlint"));
const requireAll = process.env.REQUIRE_ALL_TOOLS === "1";
const skipLinks = !hasPandoc && !requireAll ? "pandoc が見つかりません" : false;
const skipText = !hasNodeModules && !requireAll ? "npm ci を実行してください" : false;

const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "check-manuscript-"));
after(() => fs.rmSync(tmpRoot, { recursive: true, force: true }));

// 1x1 の PNG
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64"
);

let bookCount = 0;
/** 本を作る。files は { 相対パス: 内容 }。book.yaml を省略すると最小の設定を書く */
function makeBook(files) {
  const dir = path.join(tmpRoot, `book${++bookCount}`);
  const all = { "book.yaml": "title: テスト\nauthor: 試験 太郎\n", ...files };
  for (const [rel, content] of Object.entries(all)) {
    const p = path.join(dir, rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, content);
  }
  return dir;
}

function cleanEnv(extra = {}) {
  const env = { ...process.env, NO_COLOR: "1", PANDOC, ...extra };
  for (const k of ["GITHUB_ACTIONS", "FORCE_COLOR", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"]) {
    if (!(k in extra)) delete env[k];
  }
  return env;
}

/** スクリプトを同期で実行する（外部 URL の確認をしないとき） */
function run(args, extraEnv) {
  const r = spawnSync(process.execPath, [SCRIPT, ...args], { encoding: "utf8", env: cleanEnv(extraEnv) });
  return { code: r.status, out: r.stdout, err: r.stderr };
}

/** 非同期で実行する（テスト内の HTTP サーバーに接続するため、イベントループを止めない） */
function runAsync(args, extraEnv) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [SCRIPT, ...args], { env: cleanEnv(extraEnv) });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => resolve({ code, out, err }));
  });
}

const GOOD_CHAPTERS = {
  "chapters/01-intro.md": [
    "# はじめに {#sec:intro}",
    "",
    "これはテストです。[@sec:next]を参照してください。",
    "",
    "![図の説明](images/figure.png){#fig:one}",
    "",
    "図は[@fig:one]です。[次の節](#sec:next)と[自動ID](#auto-heading)へのリンクもあります。",
    "",
    "## Auto heading",
    "",
    "[メール](mailto:a@example.com)も使えます。",
    ""
  ].join("\n"),
  "chapters/02-next.md": "# 次の章 {#sec:next}\n\n本文です。\n",
  "images/figure.png": PNG
};

// ---------------------------------------------------------------------------
// 引数
// ---------------------------------------------------------------------------
describe("引数", () => {
  test("--only に text / links 以外を指定するとエラー（終了コード 2）", () => {
    const r = run(["--only", "spelling", makeBook(GOOD_CHAPTERS)]);
    assert.equal(r.code, 2);
    assert.match(r.err, /--only には text か links/);
  });

  test("不明なオプションはエラー", () => {
    const r = run(["--bogus"]);
    assert.equal(r.code, 2);
    assert.match(r.err, /不明なオプションです: --bogus/);
  });

  test("--help は使い方を表示する", () => {
    const r = run(["--help"]);
    assert.equal(r.code, 0);
    assert.match(r.out, /npm run lint/);
  });

  test("book.yaml の無いディレクトリはエラー", () => {
    const dir = path.join(tmpRoot, "empty");
    fs.mkdirSync(dir, { recursive: true });
    const r = run(["--only", "links", dir]);
    assert.equal(r.code, 2);
    assert.match(r.err, /book\.yaml がありません/);
  });
});

// ---------------------------------------------------------------------------
// リンク・参照
// ---------------------------------------------------------------------------
describe("リンク・参照", { skip: skipLinks }, () => {
  test("問題のない本は合格する", () => {
    const r = run(["--only", "links", "--no-external", makeBook(GOOD_CHAPTERS)]);
    assert.equal(r.code, 0, r.out + r.err);
    assert.match(r.out, /リンク・参照\s+✔ 問題なし/);
    assert.match(r.out, /外部 URL 0 件（確認を省略）/);
    assert.match(r.out, /すべてのチェックに合格しました/);
    assert.doesNotMatch(r.out, /表記・文章/); // --only links
  });

  test("chapters を省略すると chapters/*.md をファイル名順に使う", () => {
    const dir = makeBook({ "chapters/b.md": "# B\n", "chapters/a.md": "# A\n", "chapters/notes.txt": "x" });
    const r = run(["--only=links", "--no-external", dir]);
    assert.equal(r.code, 0, r.out + r.err);
    assert.match(r.out, /原稿 2 ファイル/);
  });

  test("壊れた参照・リンク・画像をエラーとして行番号つきで報告する", () => {
    const dir = makeBook({
      "book.yaml": "title: テスト\nauthor: 試験\ncover: images/cover.jpg\nchapters:\n  - chapters/01.md\n  - chapters/02.md\n  - chapters/99-missing.md\n",
      "chapters/01.md": [
        "# 一 {#sec:dup}",
        "",
        "[@sec:nothing]を参照。",
        "",
        "[壊れたリンク](#no-such-id)",
        "",
        "[章へのリンク](02.md)と[ファイル](../notes.txt)",
        "",
        "![無い画像](images/none.png)",
        ""
      ].join("\n"),
      "chapters/02.md": "# 二 {#sec:dup}\n\n本文。\n"
    });
    const r = run(["--only", "links", "--no-external", dir]);
    assert.equal(r.code, 1);
    const expect = [
      /3:2\s+✖ 参照先が見つかりません: @sec:nothing/,
      /5:\d+\s+✖ リンク先の見出し・ID が見つかりません: #no-such-id/,
      /7:\d+\s+✖ 原稿内の相対パスへのリンクは使えません: 02\.md（EPUB では章ファイルへのリンクは切れます/,
      /7:\d+\s+✖ 原稿内の相対パスへのリンクは使えません: \.\.\/notes\.txt（EPUB には含まれないため/,
      /9:\d+\s+✖ 画像が見つかりません: images\/none\.png/,
      /1:\d+\s+✖ ID「sec:dup」が .*01\.md と重複しています/,
      /✖ book\.yaml の chapters にある原稿が見つかりません: .*99-missing\.md/,
      /3:\d+\s+✖ 表紙画像が見つかりません: images\/cover\.jpg/
    ];
    for (const re of expect) assert.match(r.out, re);
    assert.match(r.out, /✖ エラー 8 件、警告 0 件/);
  });

  test("警告だけなら終了コード 0", () => {
    const dir = makeBook({
      "chapters/01.md": [
        "# 一",
        "",
        "@someone の引用と[電話](tel:0000)と[FTP](ftp://example.org/x)。",
        "",
        "![WebP](images/photo.webp)",
        "",
        "![外部](https://example.com/a.png)",
        ""
      ].join("\n"),
      "images/photo.webp": "RIFF"
    });
    const r = run(["--only", "links", "--no-external", dir]);
    assert.equal(r.code, 0, r.out);
    assert.match(r.out, /⚠ @someone は相互参照ではなく文献引用として扱われます/);
    assert.match(r.out, /⚠ 確認できない種類のリンクです: ftp:\/\/example\.org\/x/);
    assert.match(r.out, /⚠ Kindle で使えない可能性がある画像形式です: images\/photo\.webp/);
    assert.match(r.out, /⚠ 外部の画像は使わず images\/ に置いてください: https:\/\/example\.com\/a\.png/);
    assert.doesNotMatch(r.out, /tel:0000/);
    assert.match(r.out, /外部 URL 1 件/);
    assert.match(r.out, /エラーはありません（警告 4 件）/);
  });

  test("画像は本のディレクトリと images/ の両方から探す", () => {
    const dir = makeBook({ "chapters/01.md": "# 一\n\n![図](figure.png)\n\n![日本語](images/%E5%9B%B3.png)\n", "images/figure.png": PNG, "images/図.png": PNG });
    const r = run(["--only", "links", "--no-external", dir]);
    assert.equal(r.code, 0, r.out);
  });

  test("表のキャプションの {#tbl:id} も参照先として扱う", () => {
    const dir = makeBook({
      "chapters/01.md": "# 一\n\n[@tbl:modes]のとおり。\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n: 表の説明 {#tbl:modes}\n"
    });
    const r = run(["--only", "links", "--no-external", dir]);
    assert.equal(r.code, 0, r.out);
  });

  test("GitHub Actions では問題のある行に注釈を付ける", () => {
    const dir = makeBook({ "chapters/01.md": "# 一\n\n[壊れた](#nope)\n" });
    const r = run(["--only", "links", "--no-external", dir], { GITHUB_ACTIONS: "true" });
    assert.equal(r.code, 1);
    assert.match(r.out, /^::error file=.*01\.md,line=3,col=\d+,title=リンク・参照::リンク先の見出し・ID が見つかりません: #nope$/m);
  });

  test("pandoc が無いと分かりやすいエラー", () => {
    const r = run(["--only", "links", makeBook(GOOD_CHAPTERS)], { PANDOC: path.join(tmpRoot, "no-such-pandoc") });
    assert.equal(r.code, 2);
    assert.match(r.err, /pandoc が見つかりません/);
  });
});

// ---------------------------------------------------------------------------
// 外部 URL（テスト内の HTTP サーバーを使う）
// ---------------------------------------------------------------------------
describe("外部 URL", { skip: skipLinks }, () => {
  let server;
  let base;
  const hits = [];
  before(async () => {
    server = http.createServer((req, res) => {
      hits.push(`${req.method} ${req.url}`);
      const status = { "/ok": 200, "/gone": 404, "/broken": 500, "/head-not-allowed": req.method === "HEAD" ? 405 : 200 }[req.url] ?? 404;
      res.writeHead(status, { "Content-Type": "text/plain" });
      res.end("x");
    });
    // linkcheck.json は localhost / 127.0.0.1 を確認しない設定なので、別のループバックアドレスを使う
    await new Promise((resolve) => server.listen(0, "127.0.0.2", resolve));
    base = `http://127.0.0.2:${server.address().port}`;
  });
  after(() => server?.close());

  test("404 はエラー、500 は警告、200 と HEAD 非対応のサーバーは問題なし、除外設定の URL は確認しない", async () => {
    const dir = makeBook({
      "chapters/01.md": [
        "# 一",
        "",
        `[ok](${base}/ok) [gone](${base}/gone) [broken](${base}/broken)`,
        "",
        `[head](${base}/head-not-allowed) [ex](https://www.example.com/page)`,
        ""
      ].join("\n")
    });
    hits.length = 0;
    const r = await runAsync(["--only", "links", dir]);
    assert.equal(r.code, 1, r.out + r.err);
    assert.match(r.out, new RegExp(`3:\\d+\\s+✖ 外部リンク ${base}/gone: ページが見つかりません（HTTP 404）`));
    assert.match(r.out, new RegExp(`⚠ 外部リンク ${base}/broken: 確認できませんでした（HTTP 500`));
    assert.doesNotMatch(r.out, /\/ok:|head-not-allowed:|example\.com/);
    assert.match(r.out, /外部 URL 5 件/);
    assert.ok(hits.includes("GET /head-not-allowed"), "HEAD が失敗したら GET で確かめる");
    assert.ok(!hits.some((h) => h.includes("example")));
  });

  test("--no-external では接続しない", () => {
    const dir = makeBook({ "chapters/01.md": `# 一\n\n[gone](${base}/gone)\n` });
    hits.length = 0;
    const r = run(["--only", "links", "--no-external", dir]);
    assert.equal(r.code, 0, r.out);
    assert.deepEqual(hits, []);
  });
});

// ---------------------------------------------------------------------------
// 表記・文章（textlint）
// ---------------------------------------------------------------------------
// textlint は起動（辞書の読み込み）に数秒かかり、メモリも使うので、並行して実行しない
describe("表記・文章", { skip: skipText }, () => {
  test("問題のない原稿は合格する", async () => {
    const r = await runAsync(["--only", "text", makeBook(GOOD_CHAPTERS)]);
    assert.equal(r.code, 0, r.out + r.err);
    assert.match(r.out, /表記・文章\s+✔ 問題なし/);
    assert.doesNotMatch(r.out, /リンク・参照/);
  });

  test("表記ゆれ（prh の辞書）をエラーにし、--fix で直せる", async () => {
    const dir = makeBook({ "chapters/01.md": "# 一\n\nこの本はkindleで読めます。\n" });
    const r = await runAsync(["--only", "text", dir]);
    assert.equal(r.code, 1);
    assert.match(r.out, /3:\d+\s+✖ .*kindle => Kindle.*\(自動修正可\) \[prh\]/);

    const fixed = await runAsync(["--only", "text", "--fix", dir]);
    assert.equal(fixed.code, 0, fixed.out);
    assert.match(fixed.out, /1 ファイルを自動修正しました/);
    assert.equal(fs.readFileSync(path.join(dir, "chapters/01.md"), "utf8"), "# 一\n\nこの本はKindleで読めます。\n");
  });

  test("Pandoc の記法（囲み・属性・ルビ）を文章として検査しない", async () => {
    const dir = makeBook({
      "chapters/01.md": [
        "# 見出し {#sec:a .unnumbered}",
        "",
        "::: note",
        "囲みの中の文章です。",
        ":::",
        "",
        "{漢字|かんじ}にはルビを振ります。",
        "",
        "![図の説明](images/figure.png){#fig:a width=50%}",
        ""
      ].join("\n"),
      "images/figure.png": PNG
    });
    const r = await runAsync(["--only", "text", dir]);
    assert.equal(r.code, 0, r.out);
  });

  test("本ごとの textlint.json でルールを上書きできる", async () => {
    const chapters = { "chapters/01.md": "# 一\n\nこの本はkindleで読めます。\n" };
    const dir = makeBook({ ...chapters, "textlint.json": JSON.stringify({ rules: { prh: false } }) });
    const r = await runAsync(["--only", "text", dir]);
    assert.equal(r.code, 0, r.out);
    assert.match(r.out, /本ごとの設定: .*textlint\.json/);
  });

  test("本ごとの prh の辞書は共通の辞書に追加される", async () => {
    const dict = "version: 1\nrules:\n  - expected: 原稿\n    pattern: げんこう\n";
    const dir = makeBook({
      "chapters/01.md": "# 一\n\nこの本はkindleのげんこうです。\n",
      "dict.yml": dict,
      "textlint.json": JSON.stringify({ rules: { prh: { rulePaths: ["dict.yml"] } } })
    });
    const r = await runAsync(["--only", "text", dir]);
    assert.equal(r.code, 1);
    assert.match(r.out, /げんこう => 原稿/);
    assert.match(r.out, /kindle => Kindle/); // 共通の辞書も効いている
  });

  test("警告のルール（文の長さ）だけなら終了コード 0", async () => {
    const long = "これはとても長い文章で" + "、さらに言葉を重ねて文を長くしていき".repeat(8) + "ます。";
    const r = await runAsync(["--only", "text", makeBook({ "chapters/01.md": `# 一\n\n${long}\n` })]);
    assert.equal(r.code, 0, r.out);
    assert.match(r.out, /⚠/);
    assert.match(r.out, /エラーはありません（警告 \d+ 件）/);
  });
});

// ---------------------------------------------------------------------------
// リポジトリのサンプル
// ---------------------------------------------------------------------------
test("リポジトリのサンプル（books/*）は合格する", { skip: skipText || skipLinks }, () => {
  const r = run(["--no-external"]);
  assert.equal(r.code, 0, r.out + r.err);
  for (const name of fs.readdirSync(path.join(ROOT, "books"))) {
    if (fs.existsSync(path.join(ROOT, "books", name, "book.yaml"))) assert.match(r.out, new RegExp(name));
  }
});
