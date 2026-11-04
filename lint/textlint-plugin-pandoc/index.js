// textlint 用の Pandoc Markdown プラグイン。
//
// textlint 標準の Markdown プラグインで解析した AST を、Pandoc 独自の記法が
// 文章として検査されないように補正する。原稿のテキストそのものは変えないので、
// 報告される位置はずれず、`textlint --fix` でも原稿が壊れない。
//
//   ::: note / :::              … 囲みの行を除外し、前後を別の段落として扱う
//   # 見出し {#sec:id .class}    … 属性を除外
//   ![図](a.png){#fig:id}        … 〃
//   [AI]{.upright}               … 〃（[AI] は文章として残す）
//   {漢字|かんじ}                … 読みを除外（親文字だけを検査する）
//   : 表のキャプション {#tbl:id}  … 段落ではなく見出し相当として扱う（文末の「。」を求めない）
"use strict";

const MarkdownProcessor = require("@textlint/textlint-plugin-markdown").default.Processor;

// 行全体が囲みの開始・終了
const FENCE_LINE = /^[ \t]*:{3,}.*$/gm;
// 属性ブロック {#id .class key="value"}（ルビ {a|b} とは区別する）
const ATTRIBUTE = /[ \t]*\{(?:[#.][^{}\n]*|[A-Za-z][\w-]*=[^{}\n]*)\}/g;
// ルビ {親文字|読み} / {親文字|読|み}
const RUBY = /\{([^{}|\n]+)((?:\|[^{}|\n]+)+)\}/g;
// 表キャプション
const CAPTION_PREFIX = /^(?::|Table:)[ \t]+/;

function lineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
  return starts;
}

function makeLocator(text) {
  const starts = lineStarts(text);
  return (index) => {
    let lo = 0;
    let hi = starts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= index) lo = mid;
      else hi = mid - 1;
    }
    return { line: lo + 1, column: index - starts[lo] };
  };
}

// Str ノードの中で検査から外す範囲（ノード内の相対位置）と、そのうち段落の区切りになる範囲を返す
function hiddenSpans(value) {
  const spans = [];
  for (const m of value.matchAll(FENCE_LINE)) spans.push({ start: m.index, end: m.index + m[0].length, breaks: true });
  for (const m of value.matchAll(ATTRIBUTE)) spans.push({ start: m.index, end: m.index + m[0].length });
  for (const m of value.matchAll(RUBY)) {
    spans.push({ start: m.index, end: m.index + 1 }); // "{"
    const readingStart = m.index + 1 + m[1].length;
    spans.push({ start: readingStart, end: m.index + m[0].length }); // "|読み}"
  }
  spans.sort((a, b) => a.start - b.start);
  // 重なりをまとめる
  const merged = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s.start <= last.end) {
      last.end = Math.max(last.end, s.end);
      last.breaks = last.breaks || s.breaks;
    } else merged.push({ ...s });
  }
  return merged;
}

function makeStr(text, locate, start, end) {
  const value = text.slice(start, end);
  return {
    type: "Str",
    value,
    raw: value,
    range: [start, end],
    loc: { start: locate(start), end: locate(end) }
  };
}

const BREAK = Symbol("paragraph-break");

// 検査から外す部分は、値が空のインライン HTML ノードに置き換える。
// Str を分けるだけだと文の区切りと誤認されるが、ノードを残せば文はつながったまま扱われ、
// 多くのルールは HTML ノードを検査しない
function makeHidden(text, locate, start, end) {
  return {
    type: "Html",
    value: "",
    raw: text.slice(start, end),
    range: [start, end],
    loc: { start: locate(start), end: locate(end) }
  };
}

// Str ノードから検査対象外の部分を切り出す。囲みの行は段落の区切り（BREAK）にする
function splitStr(node, text, locate) {
  const [base, endOfNode] = node.range;
  if (text.slice(base, endOfNode) !== node.value) return [node]; // エスケープなどを含む場合は触らない
  const spans = hiddenSpans(node.value);
  if (spans.length === 0) return [node];
  const out = [];
  let cursor = base;
  let afterBreak = false;
  const emitStr = (start, end, beforeBreak) => {
    // 段落の区切りに接する側の改行・空白は落とす
    if (afterBreak) while (start < end && /\s/.test(text[start])) start++;
    if (beforeBreak) while (end > start && /\s/.test(text[end - 1])) end--;
    if (end > start) out.push(makeStr(text, locate, start, end));
  };
  for (const s of spans) {
    emitStr(cursor, base + s.start, s.breaks);
    if (s.breaks) out.push(BREAK);
    else out.push(makeHidden(text, locate, base + s.start, base + s.end));
    afterBreak = s.breaks;
    cursor = base + s.end;
  }
  emitStr(cursor, endOfNode, false);
  return out;
}

function isBlank(node) {
  return node.type === "Str" && node.value.trim() === "";
}

function isHidden(node) {
  return node.type === "Html" && node.value === "" && node.raw !== "";
}

function rebuildParent(parent, children, locate) {
  const visible = children.filter((c) => !isBlank(c));
  // 先頭・末尾の検査対象外の部分は段落に含めない
  while (visible.length && isHidden(visible[0])) visible.shift();
  while (visible.length && isHidden(visible[visible.length - 1])) visible.pop();
  if (visible.length === 0) return null;
  const start = visible[0].range[0];
  const end = visible[visible.length - 1].range[1];
  return {
    ...parent,
    children: visible,
    range: [start, end],
    loc: { start: locate(start), end: locate(end) },
    raw: undefined
  };
}

function transformInline(node, text, locate) {
  if (!node.children) return [node];
  const children = [];
  for (const child of node.children) {
    if (child.type === "Str") children.push(...splitStr(child, text, locate));
    else if (child.children) children.push(...transformInline(child, text, locate).filter((c) => c !== BREAK));
    else children.push(child);
  }
  return [{ ...node, children }];
}

// 段落・見出し・表のセルなど、インラインを子に持つブロックを補正する。複数の段落に分かれることがある
function transformTextBlock(node, text, locate) {
  const [inner] = transformInline(node, text, locate);
  const groups = [[]];
  for (const c of inner.children) {
    if (c === BREAK) groups.push([]);
    else groups[groups.length - 1].push(c);
  }
  return groups
    .map((g) => rebuildParent(node, g, locate))
    .filter(Boolean)
    .map((n) => ({ ...n, raw: text.slice(n.range[0], n.range[1]) }));
}

const TEXT_BLOCKS = new Set(["Paragraph", "Header", "TableCell"]);

function transformBlock(node, text, locate) {
  if (TEXT_BLOCKS.has(node.type)) return transformTextBlock(node, text, locate);
  if (!node.children) return [node];
  const children = [];
  for (const child of node.children) {
    for (const t of transformBlock(child, text, locate)) children.push(t);
  }
  markCaptions(children, text, locate);
  return [{ ...node, children }];
}

// 表の直前・直後にある「: キャプション」段落を見出し相当にする
function markCaptions(children, text, locate) {
  children.forEach((node, i) => {
    if (node.type !== "Paragraph") return;
    const prev = children[i - 1];
    const next = children[i + 1];
    if (!((prev && prev.type === "Table") || (next && next.type === "Table"))) return;
    const first = node.children[0];
    if (!first || first.type !== "Str") return;
    const m = first.value.match(CAPTION_PREFIX);
    if (!m) return;
    const rest = makeStr(text, locate, first.range[0] + m[0].length, first.range[1]);
    const newChildren = [rest, ...node.children.slice(1)].filter((c) => !isBlank(c));
    const rebuilt = rebuildParent(node, newChildren, locate);
    if (!rebuilt) return;
    children[i] = { ...rebuilt, type: "Header", depth: 6, raw: text.slice(rebuilt.range[0], rebuilt.range[1]) };
  });
}

class PandocProcessor extends MarkdownProcessor {
  processor(ext) {
    const base = super.processor(ext);
    return {
      preProcess(text, filePath) {
        const ast = base.preProcess(text, filePath);
        const locate = makeLocator(text);
        const [root] = transformBlock(ast, text, locate);
        return { text, ast: root };
      },
      postProcess: base.postProcess
    };
  }
}

module.exports = { Processor: PandocProcessor };
