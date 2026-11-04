#!/usr/bin/env node
// 原稿の品質チェック: 表記ゆれ・文章（textlint）と、リンク切れ・参照ミスをまとめて検査する。
//
// 使い方:
//   npm run lint                               # books/ 以下の全ての本
//   npm run lint -- books/my-book              # 1 冊だけ
//   npm run lint -- --fix                      # textlint で自動修正できるものを直す
//   npm run lint -- --no-external              # 外部 URL の確認を省く（オフライン時など）
//   npm run lint -- --only text                # 表記・文章だけ（links でリンクだけ）
//
// 終了コード: エラーが 1 件でもあれば 1。警告だけなら 0。
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BOOKS_DIR = path.join(ROOT, "books");
const LINT_DIR = path.join(ROOT, "lint");
const IN_CI = process.env.GITHUB_ACTIONS === "true";

// ---------------------------------------------------------------------------
// 表示
// ---------------------------------------------------------------------------
const useColor = (process.stdout.isTTY || IN_CI || process.env.FORCE_COLOR) && !process.env.NO_COLOR;
const paint = (code) => (s) => (useColor ? `\x1b[${code}m${s}\x1b[0m` : String(s));
const c = { red: paint(31), yellow: paint(33), green: paint(32), cyan: paint(36), gray: paint(90), bold: paint(1) };
const ICON = { error: c.red("✖"), warning: c.yellow("⚠"), ok: c.green("✔") };

const out = (s = "") => process.stdout.write(s + "\n");
// 全角文字を 2 桁として右を空白で埋める
const width = (s) => [...s].reduce((w, ch) => w + (/[\u1100-\uffff]/.test(ch) ? 2 : 1), 0);
const pad = (s, n) => s + " ".repeat(Math.max(0, n - width(s)));
const rel = (p) => {
  const r = path.relative(ROOT, p);
  return r.startsWith("..") ? p : r.split(path.sep).join("/");
};

// GitHub Actions では、問題のある行に注釈（アノテーション）を付ける
function annotate(problem) {
  if (!IN_CI) return;
  const esc = (s) => String(s).replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
  const props = [`file=${rel(problem.file)}`];
  if (problem.line) props.push(`line=${problem.line}`);
  if (problem.column) props.push(`col=${problem.column}`);
  props.push(`title=${esc(problem.category)}`);
  out(`::${problem.severity === "error" ? "error" : "warning"} ${props.join(",")}::${esc(problem.message)}`);
}

// ---------------------------------------------------------------------------
// 引数
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const opts = { books: [], fix: false, external: true, only: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--fix") opts.fix = true;
    else if (a === "--no-external") opts.external = false;
    else if (a === "--only") opts.only = argv[++i];
    else if (a.startsWith("--only=")) opts.only = a.slice("--only=".length);
    else if (a === "-h" || a === "--help") {
      out(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n").slice(1, 11).map((l) => l.replace(/^\/\/ ?/, "")).join("\n"));
      process.exit(0);
    } else if (a.startsWith("-")) {
      throw new Error(`不明なオプションです: ${a}`);
    } else opts.books.push(path.resolve(a));
  }
  if (opts.only && !["text", "links"].includes(opts.only)) throw new Error("--only には text か links を指定してください");
  if (opts.books.length === 0) {
    opts.books = fs
      .readdirSync(BOOKS_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory() && fs.existsSync(path.join(BOOKS_DIR, d.name, "book.yaml")))
      .map((d) => path.join(BOOKS_DIR, d.name))
      .sort();
  }
  return opts;
}

// ---------------------------------------------------------------------------
// 本の設定（scripts/build.py と同じ規則で原稿ファイルを決める）
// ---------------------------------------------------------------------------
function loadBook(bookDir) {
  const yamlPath = path.join(bookDir, "book.yaml");
  if (!fs.existsSync(yamlPath)) throw new Error(`${rel(bookDir)} に book.yaml がありません`);
  const cfg = parseYaml(fs.readFileSync(yamlPath, "utf8")) ?? {};
  let chapters = [].concat(cfg.chapters ?? []).map((p) => path.join(bookDir, p));
  if (chapters.length === 0) {
    const dir = path.join(bookDir, "chapters");
    chapters = fs.existsSync(dir)
      ? fs.readdirSync(dir).filter((f) => f.endsWith(".md")).sort().map((f) => path.join(dir, f))
      : [];
  }
  return {
    dir: bookDir,
    name: path.basename(bookDir),
    yamlPath,
    cfg,
    chapters,
    writingMode: cfg.layout?.writing_mode === "vertical" ? "vertical" : "horizontal"
  };
}

// 原稿内の文字列から行・列を求める（見つからなければ 1 行目）
function locate(text, needle, from = 0) {
  const idx = needle ? text.indexOf(needle, from) : -1;
  if (idx < 0) return { line: undefined, column: undefined, index: -1 };
  const before = text.slice(0, idx);
  const line = before.split("\n").length;
  return { line, column: idx - before.lastIndexOf("\n"), index: idx };
}

// ---------------------------------------------------------------------------
// 1. 表記・文章のチェック（textlint）
// ---------------------------------------------------------------------------
const isPlainObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

function deepMerge(base, over) {
  if (!isPlainObject(base) || !isPlainObject(over)) return over;
  const result = { ...base };
  for (const [k, v] of Object.entries(over)) {
    result[k] = k in base ? deepMerge(base[k], v) : v;
  }
  return result;
}

// prh の辞書パスを絶対パスにする（本ごとの設定では辞書を追加できる）
function absolutizePrh(config, baseDir) {
  const prh = config?.rules?.prh;
  if (isPlainObject(prh) && Array.isArray(prh.rulePaths)) {
    prh.rulePaths = prh.rulePaths.map((p) => path.resolve(baseDir, p));
  }
  return config;
}

// ルート の .textlintrc.json に、本ごとの textlint.json（任意）を重ねる
function textlintConfigFor(book) {
  const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
  const base = absolutizePrh(readJson(path.join(ROOT, ".textlintrc.json")), ROOT);
  const overridePath = path.join(book.dir, "textlint.json");
  if (!fs.existsSync(overridePath)) return { config: base, overridePath: null };
  const over = absolutizePrh(readJson(overridePath), book.dir);
  const merged = deepMerge(base, over);
  const basePaths = base.rules?.prh?.rulePaths ?? [];
  const overPaths = over.rules?.prh?.rulePaths;
  if (overPaths && isPlainObject(merged.rules?.prh)) merged.rules.prh.rulePaths = [...new Set([...basePaths, ...overPaths])];
  return { config: merged, overridePath };
}

let textlintModules;
async function loadTextlint() {
  if (!textlintModules) {
    try {
      const [{ createLinter }, { loadPackagesFromRawConfig }, { TextlintKernelDescriptor }, markdown] = await Promise.all([
        import("textlint"),
        import("@textlint/config-loader"),
        import("@textlint/kernel"),
        import("@textlint/textlint-plugin-markdown")
      ]);
      const builtInPlugins = [{ pluginId: "@textlint/textlint-plugin-markdown", plugin: markdown.default.default ?? markdown.default, options: true }];
      textlintModules = { createLinter, loadPackagesFromRawConfig, TextlintKernelDescriptor, builtInPlugins };
    } catch (e) {
      throw new Error(`textlint が見つかりません。先に npm install を実行してください（${e.message}）`);
    }
  }
  return textlintModules;
}

async function createBookLinter(book) {
  const { createLinter, loadPackagesFromRawConfig, TextlintKernelDescriptor, builtInPlugins } = await loadTextlint();
  const { config, overridePath } = textlintConfigFor(book);
  const loaded = await loadPackagesFromRawConfig({ rawConfig: config, node_modulesDir: path.join(ROOT, "node_modules") });
  if (!loaded.ok) {
    const detail = (loaded.error?.errors ?? []).map((e) => e.message).join("\n  ");
    throw new Error(`textlint の設定を読み込めません: ${loaded.error?.message ?? ""}\n  ${detail}`);
  }
  const descriptor = new TextlintKernelDescriptor({
    rules: loaded.config.rules,
    filterRules: loaded.config.filterRules,
    // Pandoc 記法に対応したプラグインを、標準の Markdown プラグインより先に使う
    plugins: [...loaded.config.plugins, ...builtInPlugins],
    configBaseDir: ROOT
  });
  return { linter: createLinter({ descriptor, cwd: ROOT }), overridePath };
}

const SEVERITY = { 1: "warning", 2: "error", 3: "info" };

async function checkText(book, opts) {
  const problems = [];
  const { linter, overridePath } = await createBookLinter(book);
  let fixedFiles = 0;
  for (const file of book.chapters) {
    if (!fs.existsSync(file)) continue; // リンクチェック側で報告する
    let text = fs.readFileSync(file, "utf8");
    if (opts.fix) {
      const fixed = await linter.fixText(text, file);
      if (fixed.output !== text) {
        fs.writeFileSync(file, fixed.output);
        text = fixed.output;
        fixedFiles++;
      }
    }
    const result = await linter.lintText(text, file);
    for (const m of result.messages) {
      const severity = SEVERITY[m.severity] ?? "error";
      if (severity === "info") continue;
      const [first, ...rest] = String(m.message).split("\n");
      problems.push({
        file,
        line: m.line,
        column: m.column,
        severity,
        category: "表記・文章",
        message: first.trim(),
        detail: rest.join("\n").trim(),
        rule: m.ruleId,
        fixable: Boolean(m.fix)
      });
    }
  }
  return { problems, fixedFiles, overridePath };
}

// ---------------------------------------------------------------------------
// 2. リンク・参照のチェック
// ---------------------------------------------------------------------------
const PANDOC_FROM =
  "markdown+east_asian_line_breaks+ascii_identifiers+bracketed_spans+fenced_divs+footnotes+pipe_tables+grid_tables+implicit_figures+link_attributes";
const CROSSREF_PREFIX = /^(fig|tbl|lst|sec):/;

function loadLinkConfig() {
  const p = path.join(LINT_DIR, "linkcheck.json");
  const defaults = { external: { timeout: 15000, retries: 2, concurrency: 8, ignore: [] }, imageExtensions: [".jpg", ".jpeg", ".png", ".gif", ".svg"] };
  if (!fs.existsSync(p)) return defaults;
  const cfg = deepMerge(defaults, JSON.parse(fs.readFileSync(p, "utf8")));
  cfg.external.ignore = (cfg.external.ignore ?? []).map((r) => new RegExp(r));
  return cfg;
}

let pandocChecked = false;
function pandocAst(file, pandoc) {
  const r = spawnSync(pandoc, ["--from", PANDOC_FROM, "--to", "json", file], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (r.error) {
    if (r.error.code === "ENOENT" && !pandocChecked) {
      throw new Error(`pandoc が見つかりません（${pandoc}）。bash scripts/setup.sh を実行するか、環境変数 PANDOC を指定してください`);
    }
    throw r.error;
  }
  pandocChecked = true;
  if (r.status !== 0) throw new Error(`pandoc が ${rel(file)} を読み込めませんでした:\n${r.stderr}`);
  return JSON.parse(r.stdout);
}

// Pandoc の JSON AST を走査し、ID・リンク・画像・相互参照を集める
const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function collectFromAst(ast, text) {
  const ids = [];
  const links = [];
  const images = [];
  const cites = [];
  const attrId = (attr) => (Array.isArray(attr) && typeof attr[0] === "string" && attr[0] ? attr[0] : null);
  const walk = (node) => {
    if (Array.isArray(node)) return node.forEach(walk);
    if (!isPlainObject(node)) return;
    const { t, c: content } = node;
    switch (t) {
      case "Header": {
        // {#id} を書いた見出しか、見出しの文字から自動で付いた ID か
        const id = attrId(content[1]);
        if (id) ids.push({ id, explicit: new RegExp(`\\{[^{}]*#${escapeRegExp(id)}[\\s}]`).test(text) });
        break;
      }
      case "Div":
      case "Span":
      case "CodeBlock":
      case "Figure":
      case "Table":
      case "Code": {
        const id = attrId(content[0]);
        if (id) ids.push({ id, explicit: true });
        break;
      }
      case "Link":
        if (attrId(content[0])) ids.push({ id: attrId(content[0]), explicit: true });
        links.push(content[2][0]);
        break;
      case "Image":
        if (attrId(content[0])) ids.push({ id: attrId(content[0]), explicit: true });
        images.push(content[2][0]);
        break;
      case "Cite":
        for (const citation of content[0]) cites.push(citation.citationId);
        break;
      case "Str": {
        // pandoc 3.1 では表キャプションの {#tbl:id} が文字列のまま残る（filters/crossref.lua と同じ扱い）
        const m = /^\{#([^\s{}]+)\}$/.exec(content);
        if (m) ids.push({ id: m[1], explicit: true });
        break;
      }
    }
    if (content !== undefined && typeof content !== "string") walk(content);
  };
  walk(ast.blocks);
  return { ids, links, images, cites };
}

// 見出しの自動 ID は pandoc が本全体で重複しないよう連番を付け直すため、ファイル単位では確定しない。
// 明示した ID（{#sec:xxx} など）を推奨し、自動 ID へのリンクは存在確認だけにとどめる。
function checkLinksLocal(book, linkCfg, pandoc) {
  const problems = [];
  const externals = [];
  const perFile = [];
  const explicitIds = new Map(); // id -> 最初に定義したファイル

  const push = (file, text, needle, severity, message, from = 0) => {
    const loc = locate(text, needle, from);
    problems.push({ file, line: loc.line, column: loc.column, severity, category: "リンク・参照", message });
    return loc.index;
  };

  for (const file of book.chapters) {
    if (!fs.existsSync(file)) {
      problems.push({ file: book.yamlPath, severity: "error", category: "リンク・参照", message: `book.yaml の chapters にある原稿が見つかりません: ${rel(file)}` });
      continue;
    }
    const text = fs.readFileSync(file, "utf8");
    const data = collectFromAst(pandocAst(file, pandoc), text);
    perFile.push({ file, text, data });
    for (const { id, explicit } of data.ids) {
      if (!explicit) continue;
      if (explicitIds.has(id) && explicitIds.get(id) !== file) {
        push(file, text, `#${id}`, "error", `ID「${id}」が ${rel(explicitIds.get(id))} と重複しています`);
      } else explicitIds.set(id, file);
    }
  }
  const allIds = new Set(perFile.flatMap((f) => f.data.ids.map((i) => i.id)));

  const resourceDirs = [book.dir, path.join(book.dir, "images")];
  const findResource = (p) => resourceDirs.map((d) => path.resolve(d, p)).find((full) => fs.existsSync(full));

  for (const { file, text, data } of perFile) {
    // 相互参照 @sec:xxx / @fig:xxx / @tbl:xxx / @lst:xxx
    const seenCites = new Set();
    for (const id of data.cites) {
      if (seenCites.has(id)) continue;
      seenCites.add(id);
      if (CROSSREF_PREFIX.test(id)) {
        if (!allIds.has(id)) push(file, text, `@${id}`, "error", `参照先が見つかりません: @${id}（{#${id}} を付けた見出し・図・表・リストがありません）`);
      } else {
        push(file, text, `@${id}`, "warning", `@${id} は相互参照ではなく文献引用として扱われます（参照なら @sec: / @fig: / @tbl: / @lst: を付けてください）`);
      }
    }

    // リンク
    let from = 0;
    for (const url of data.links) {
      if (/^(mailto|tel):/i.test(url)) continue;
      if (/^https?:\/\//i.test(url)) {
        externals.push({ url, file, text });
        continue;
      }
      if (url.startsWith("#")) {
        const id = decodeURIComponent(url.slice(1));
        if (!allIds.has(id)) {
          from = Math.max(0, push(file, text, url, "error", `リンク先の見出し・ID が見つかりません: ${url}`, from)) + 1;
        }
        continue;
      }
      if (/^[a-z][a-z0-9+.-]*:/i.test(url)) {
        push(file, text, url, "warning", `確認できない種類のリンクです: ${url}`);
        continue;
      }
      const [target] = url.split("#");
      const hint = /\.md$/i.test(target) ? "（EPUB では章ファイルへのリンクは切れます。@sec:ID の相互参照を使ってください）" : "（EPUB には含まれないため、リンクは切れます）";
      push(file, text, url, "error", `原稿内の相対パスへのリンクは使えません: ${url}${hint}`);
    }

    // 画像
    for (const src of data.images) {
      if (/^https?:\/\//i.test(src)) {
        push(file, text, src, "warning", `外部の画像は使わず images/ に置いてください: ${src}`);
        externals.push({ url: src, file, text });
        continue;
      }
      if (/^data:/i.test(src)) continue;
      const decoded = decodeURIComponent(src);
      if (!findResource(decoded)) {
        push(file, text, src, "error", `画像が見つかりません: ${src}（${resourceDirs.map((d) => rel(d) + "/").join(" と ")} から探しました）`);
        continue;
      }
      const ext = path.extname(decoded).toLowerCase();
      if (!linkCfg.imageExtensions.includes(ext)) {
        push(file, text, src, "warning", `Kindle で使えない可能性がある画像形式です: ${src}（${linkCfg.imageExtensions.join(" / ")} を推奨）`);
      }
    }
  }

  // 表紙
  if (book.cfg.cover && !fs.existsSync(path.join(book.dir, book.cfg.cover))) {
    const yamlText = fs.readFileSync(book.yamlPath, "utf8");
    push(book.yamlPath, yamlText, book.cfg.cover, "error", `表紙画像が見つかりません: ${book.cfg.cover}`);
  }

  return { problems, externals };
}

// ---- 外部 URL ----
const externalCache = new Map();

async function fetchStatus(url, cfg) {
  const headers = { "User-Agent": "Mozilla/5.0 (compatible; kindle-book-template-linkcheck/1.0)", Accept: "*/*" };
  let lastError;
  for (let attempt = 0; attempt <= cfg.retries; attempt++) {
    for (const method of ["HEAD", "GET"]) {
      try {
        const res = await fetch(url, { method, headers, redirect: "follow", signal: AbortSignal.timeout(cfg.timeout) });
        if (method === "GET") res.body?.cancel().catch(() => {});
        // HEAD を受け付けないサーバーがあるので、失敗したら GET で確かめる
        if (method === "HEAD" && res.status >= 400) continue;
        return { status: res.status };
      } catch (e) {
        lastError = e;
        if (method === "HEAD") continue;
      }
    }
    if (attempt < cfg.retries) await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
  }
  return { error: lastError };
}

function classifyExternal(result) {
  if (result.status !== undefined) {
    const s = result.status;
    if (s < 400) return null;
    if (s === 404 || s === 410) return { severity: "error", reason: `ページが見つかりません（HTTP ${s}）` };
    return { severity: "warning", reason: `確認できませんでした（HTTP ${s}。アクセス制限や一時的な障害の可能性があります）` };
  }
  // fetch のエラーは cause が入れ子になっているので、いちばん具体的なものを探す
  const chain = [];
  for (let e = result.error; e && chain.length < 5; e = e.cause) chain.push(e);
  const code = chain.map((e) => e.code).find((v) => typeof v === "string") ?? chain.map((e) => e.name).find((n) => n === "TimeoutError");
  const detail = chain.map((e) => e.message).filter(Boolean).pop() ?? "不明なエラー";
  if (code === "ENOTFOUND") return { severity: "error", reason: "ドメインが見つかりません（DNS）" };
  if (String(code).startsWith("ERR_TLS") || /certificate/i.test(detail)) {
    return { severity: "error", reason: `HTTPS の証明書に問題があります（${code}）` };
  }
  if (code === "TimeoutError") return { severity: "warning", reason: "タイムアウトしました" };
  return { severity: "warning", reason: `接続できませんでした（${code ? `${code}: ` : ""}${detail}）` };
}

async function checkExternal(externals, cfg) {
  const problems = [];
  const todo = [...new Set(externals.map((e) => e.url))].filter((u) => !externalCache.has(u) && !cfg.ignore.some((r) => r.test(u)));
  const results = new Map();
  let next = 0;
  const worker = async () => {
    while (next < todo.length) {
      const url = todo[next++];
      results.set(url, await fetchStatus(url, cfg));
    }
  };
  await Promise.all(Array.from({ length: Math.min(cfg.concurrency, todo.length) }, worker));
  // 1 件も HTTP の応答がなければ、ネットワークにつながっていないとみなしてエラーにしない
  const offline = todo.length > 0 && [...results.values()].every((r) => r.status === undefined);
  for (const [url, result] of results) {
    const verdict = classifyExternal(result);
    externalCache.set(url, offline && verdict ? { severity: "warning", reason: `${verdict.reason}。ネットワークに接続できないようです（--no-external で確認を省略できます）` } : verdict);
  }
  const reported = new Set();
  for (const { url, file, text } of externals) {
    const verdict = externalCache.get(url);
    if (!verdict || reported.has(file + url)) continue;
    reported.add(file + url);
    const loc = locate(text, url);
    problems.push({ file, line: loc.line, column: loc.column, severity: verdict.severity, category: "リンク・参照", message: `外部リンク ${url}: ${verdict.reason}` });
  }
  return { problems, checked: todo.length };
}

// ---------------------------------------------------------------------------
// 結果の表示
// ---------------------------------------------------------------------------
function count(problems) {
  return {
    errors: problems.filter((p) => p.severity === "error").length,
    warnings: problems.filter((p) => p.severity === "warning").length
  };
}

function statusText({ errors, warnings }) {
  if (errors) return c.red(`✖ エラー ${errors} 件`) + (warnings ? c.yellow(` / 警告 ${warnings} 件`) : "");
  if (warnings) return c.yellow(`⚠ 警告 ${warnings} 件`);
  return c.green("✔ 問題なし");
}

function printSection(title, problems, note) {
  out(`  ${c.bold(pad(title, 14))} ${statusText(count(problems))}${note ? c.gray("  " + note) : ""}`);
  const byFile = new Map();
  for (const p of problems) {
    if (!byFile.has(p.file)) byFile.set(p.file, []);
    byFile.get(p.file).push(p);
  }
  for (const [file, list] of [...byFile].sort(([a], [b]) => a.localeCompare(b))) {
    out(`    ${c.cyan(rel(file))}`);
    list.sort((a, b) => (a.line ?? 0) - (b.line ?? 0) || (a.column ?? 0) - (b.column ?? 0));
    for (const p of list) {
      const pos = p.line ? `${p.line}:${p.column ?? 1}` : "-";
      const rule = p.rule ? c.gray(` [${p.rule}]`) : "";
      const fix = p.fixable ? c.green(" (自動修正可)") : "";
      out(`      ${c.gray(pos.padStart(7))}  ${ICON[p.severity]} ${p.message}${fix}${rule}`);
      annotate(p);
    }
  }
}

// ---------------------------------------------------------------------------
// メイン
// ---------------------------------------------------------------------------
async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const pandoc = process.env.PANDOC || "pandoc";
  const linkCfg = loadLinkConfig();
  const summary = [];

  for (const bookDir of opts.books) {
    const book = loadBook(bookDir);
    const mode = book.writingMode === "vertical" ? "縦書き" : "横書き";
    out("");
    out(c.bold(`📖 ${book.name}`) + c.gray(`（${mode}・原稿 ${book.chapters.length} ファイル）`));

    const row = { name: book.name };
    if (opts.only !== "links") {
      const { problems, fixedFiles, overridePath } = await checkText(book, opts);
      const notes = [];
      if (overridePath) notes.push(`本ごとの設定: ${rel(overridePath)}`);
      if (fixedFiles) notes.push(`${fixedFiles} ファイルを自動修正しました`);
      printSection("表記・文章", problems, notes.join(" / "));
      row.text = count(problems);
    }
    if (opts.only !== "text") {
      const { problems, externals } = checkLinksLocal(book, linkCfg, pandoc);
      let note = `外部 URL ${new Set(externals.map((e) => e.url)).size} 件`;
      if (opts.external) {
        const ext = await checkExternal(externals, linkCfg.external);
        problems.push(...ext.problems);
      } else note += "（確認を省略）";
      printSection("リンク・参照", problems, note);
      row.links = count(problems);
    }
    summary.push(row);
  }

  // まとめ
  const total = { errors: 0, warnings: 0 };
  out("");
  out(c.bold("─".repeat(56)));
  out(c.bold("まとめ"));
  for (const row of summary) {
    const parts = [];
    for (const [key, label] of [["text", "表記・文章"], ["links", "リンク・参照"]]) {
      if (!row[key]) continue;
      total.errors += row[key].errors;
      total.warnings += row[key].warnings;
      parts.push(`${label} ${statusText(row[key])}`);
    }
    out(`  ${pad(row.name, 22)} ${parts.join("   ")}`);
  }
  out("");
  if (total.errors) {
    out(c.red(c.bold(`✖ エラー ${total.errors} 件、警告 ${total.warnings} 件`)));
    out(c.gray("  「自動修正可」の指摘は npm run lint:fix で直せます。誤検出は README の「原稿のチェック」を参照してください。"));
  } else if (total.warnings) {
    out(c.yellow(c.bold(`⚠ エラーはありません（警告 ${total.warnings} 件）`)));
  } else {
    out(c.green(c.bold("✔ すべてのチェックに合格しました")));
  }
  return total.errors ? 1 : 0;
}

// プロキシ環境（HTTPS_PROXY）では、Node.js の fetch にプロキシを使わせるため設定して起動し直す
if ((process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy) && !process.env.NODE_USE_ENV_PROXY) {
  const r = spawnSync(process.execPath, [...process.execArgv, "--no-warnings", fileURLToPath(import.meta.url), ...process.argv.slice(2)], {
    stdio: "inherit",
    env: { ...process.env, NODE_USE_ENV_PROXY: "1", ...(process.stdout.isTTY ? { FORCE_COLOR: "1" } : {}) }
  });
  process.exit(r.status ?? 2);
}

main().then(
  (code) => process.exit(code),
  (e) => {
    process.stderr.write(c.red(`エラー: ${e.message}`) + "\n");
    process.exit(2);
  }
);
