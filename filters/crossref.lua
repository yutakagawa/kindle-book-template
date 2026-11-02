--[[
crossref.lua — 章番号・図番号・表番号・リスト番号と相互参照

  # はじめに {.unnumbered}        … 番号なしの章（まえがき・あとがき等）
  # 付録 {.appendix}              … 付録（付録A, 付録B …）

  ![キャプション](images/a.png){#fig:arch}
  : 表のキャプション {#tbl:price}
  ```{.python #lst:hello caption="Hello World"}

  本文中で @fig:arch / @tbl:price / @lst:hello / @sec:intro と書くと
  「図1.1」「表2.3」「リスト1.2」「第1章」のようなリンクに置き換わる。

ラベルの書式は book.yaml の layout で変更できる（build.py がメタデータ kbt に渡す）。
]]

local cfg = {
  number_chapters = true,
  chapter_label = "第{n}章",
  appendix_label = "付録{n}",
  figure_label = "図{c}.{n}",
  table_label = "表{c}.{n}",
  listing_label = "リスト{c}.{n}",
  caption_separator = "　",
}

local chapter = 0          -- 本章カウンタ
local appendix = 0         -- 付録カウンタ
local current = nil        -- 図番号の {c} に入る文字列（"1", "A" など）
local counters = { fig = 0, tbl = 0, lst = 0 }
local labels = {}          -- id -> 表示ラベル
local warned = {}

local function fmt(template, c, n)
  return (template:gsub("{c}", c or ""):gsub("{n}", tostring(n or "")))
end

local function alpha(n)
  return string.char(64 + n)  -- 1 -> A
end

local function next_label(kind, template)
  counters[kind] = counters[kind] + 1
  if current then
    return fmt(template, current, counters[kind])
  end
  -- 章番号なし（まえがき等）の中の図は通し番号だけにする
  return fmt(template:gsub("{c}[%.%-]?", ""), nil, counters[kind])
end

local function label_inlines(text, cls)
  return pandoc.Span({ pandoc.Str(text) }, pandoc.Attr("", { cls }))
end

local function prepend_caption(caption_blocks, text, cls)
  local prefix = { label_inlines(text, cls), pandoc.Str(cfg.caption_separator) }
  if #caption_blocks == 0 then
    return { pandoc.Plain({ label_inlines(text, cls) }) }
  end
  local first = caption_blocks[1]
  if first.content then
    local content = pandoc.List(prefix)
    content:extend(first.content)
    first.content = content
  end
  return caption_blocks
end

-- pandoc 3.1 系では表キャプションの {#tbl:id} が属性にならず文字列のまま残るので取り出す
local function extract_trailing_id(blocks)
  if #blocks == 0 then return nil end
  local inl = blocks[#blocks].content
  if not inl or #inl == 0 then return nil end
  local last = inl[#inl]
  if last.t == "Str" then
    local id = last.text:match("^{#([%w:_%-%.]+)}$")
    if id then
      inl:remove(#inl)
      if #inl > 0 and inl[#inl].t == "Space" then inl:remove(#inl) end
      return id
    end
  end
  return nil
end

local function read_config(meta)
  local k = meta.kbt
  if not k then return end
  for key, _ in pairs(cfg) do
    local v = k[key]
    if v ~= nil then
      if type(v) == "boolean" then
        cfg[key] = v
      else
        cfg[key] = pandoc.utils.stringify(v)
      end
    end
  end
end

local numbering = {
  traverse = "topdown",

  Header = function(h)
    if h.level ~= 1 then
      if h.identifier ~= "" then labels[h.identifier] = labels[h.identifier] or pandoc.utils.stringify(h.content) end
      return nil
    end
    counters = { fig = 0, tbl = 0, lst = 0 }
    local label
    if h.classes:includes("unnumbered") then
      current = nil
    elseif h.classes:includes("appendix") then
      appendix = appendix + 1
      current = alpha(appendix)
      label = fmt(cfg.appendix_label, nil, current)
    else
      chapter = chapter + 1
      current = tostring(chapter)
      label = fmt(cfg.chapter_label, nil, chapter)
    end
    if label and cfg.number_chapters then
      local content = pandoc.List({ label_inlines(label, "chapter-number"), pandoc.Space() })
      content:extend(h.content)
      h.content = content
      if h.identifier ~= "" then labels[h.identifier] = label end
    elseif h.identifier ~= "" then
      labels[h.identifier] = pandoc.utils.stringify(h.content)
    end
    return h
  end,

  Figure = function(fig)
    if #fig.caption.long == 0 then return nil end
    local label = next_label("fig", cfg.figure_label)
    if fig.identifier ~= "" then labels[fig.identifier] = label end
    fig.caption.long = prepend_caption(fig.caption.long, label, "figure-label")
    return fig
  end,

  Table = function(tbl)
    if #tbl.caption.long == 0 then return nil end
    local id = extract_trailing_id(tbl.caption.long)
    if id and tbl.identifier == "" then tbl.identifier = id end
    local label = next_label("tbl", cfg.table_label)
    if tbl.identifier ~= "" then labels[tbl.identifier] = label end
    tbl.caption.long = prepend_caption(tbl.caption.long, label, "table-label")
    return tbl
  end,

  CodeBlock = function(cb)
    local caption = cb.attributes["caption"]
    if not caption then return nil end
    cb.attributes["caption"] = nil
    local label = next_label("lst", cfg.listing_label)
    local id = cb.identifier
    cb.identifier = ""
    if id ~= "" then labels[id] = label end
    local cap_inlines = pandoc.List({ label_inlines(label, "listing-label"), pandoc.Str(cfg.caption_separator) })
    cap_inlines:extend(pandoc.utils.blocks_to_inlines(pandoc.read(caption, "markdown").blocks))
    local title = pandoc.Div({ pandoc.Plain(cap_inlines) }, pandoc.Attr("", { "listing-caption" }))
    -- 戻り値の Div の中身は topdown 走査で再訪されないよう、そのまま返す
    return pandoc.Div({ title, cb }, pandoc.Attr(id, { "listing" })), false
  end,
}

local references = {
  Cite = function(cite)
    local out = pandoc.List()
    for i, c in ipairs(cite.citations) do
      local id = c.id
      local label = labels[id]
      if label then
        if i > 1 then out:insert(pandoc.Str("、")) end
        out:extend(c.prefix)
        out:insert(pandoc.Link({ pandoc.Str(label) }, "#" .. id, "", pandoc.Attr("", { "xref" })))
        out:extend(c.suffix)
      elseif id:match("^fig:") or id:match("^tbl:") or id:match("^lst:") or id:match("^sec:") then
        if not warned[id] then
          io.stderr:write("[crossref] 警告: 参照先が見つかりません: @" .. id .. "\n")
          warned[id] = true
        end
        return nil
      else
        return nil
      end
    end
    return out
  end,
}

function Pandoc(doc)
  read_config(doc.meta)
  doc = doc:walk(numbering)
  doc = doc:walk(references)
  return doc
end
