--[[
vertical.lua — 縦書き（vertical-rl）用の調整

  * 縦中横: 前後が全角文字の半角数字（既定 2 桁まで）と「!!」「!?」「?!」を
    <span class="tcy"> で囲み、1 文字分の幅に横並びで収める
  * コードブロックと表を <div class="v-sideways"> などで包み、CSS で表示方式を切り替える
      sideways   … 横組みを 90° 回した表示（既定。長いコードも途切れない）
      horizontal … 縦書きページ内に横組みブロックを置く（読みやすいが、ページ高を超えると切れる）
      vertical   … 縦組みのまま（英数字は横倒し、和文は正立）

横書きモードでは何もしない。設定は book.yaml の layout.vertical（build.py がメタデータ kbt に渡す）。
手動指定: [12]{.tcy}（縦中横） / [API]{.upright}（正立） / [ABC]{.sideways}（横倒し）
]]

local enabled = false
local tcy_max = 2
local code_mode = "sideways"
local table_mode = "sideways"

local function is_ascii_alnum_or_punct(ch)
  return ch ~= nil and ch:byte() < 128 and ch:match("[%w%p]") ~= nil
end

local function split_tcy(text)
  if not text:find("[%d!?]") then return nil end
  local chars = {}
  for _, c in utf8.codes(text) do chars[#chars + 1] = utf8.char(c) end
  local out = pandoc.List()
  local buf = {}
  local changed = false
  local i = 1
  while i <= #chars do
    local j = i
    local run_type
    if chars[i]:match("^%d$") then
      run_type = "digit"
      while j + 1 <= #chars and chars[j + 1]:match("^%d$") do j = j + 1 end
    elseif chars[i] == "!" or chars[i] == "?" then
      run_type = "excl"
      while j + 1 <= #chars and (chars[j + 1] == "!" or chars[j + 1] == "?") do j = j + 1 end
    end
    local len = j - i + 1
    local prev, nxt = chars[i - 1], chars[j + 1]
    local isolated = not is_ascii_alnum_or_punct(prev) and not is_ascii_alnum_or_punct(nxt)
    local ok = run_type and isolated and (
      (run_type == "digit" and len <= tcy_max) or (run_type == "excl" and len == 2))
    -- 前後とも半角スペース（または段落の端）の場合は英文の文脈とみなし対象外
    if ok and prev == nil and nxt == nil then ok = false end
    if ok then
      if #buf > 0 then out:insert(pandoc.Str(table.concat(buf))); buf = {} end
      out:insert(pandoc.Span({ pandoc.Str(table.concat(chars, "", i, j)) }, pandoc.Attr("", { "tcy" })))
      changed = true
    else
      for k = i, j do buf[#buf + 1] = chars[k] end
    end
    i = j + 1
  end
  if not changed then return nil end
  if #buf > 0 then out:insert(pandoc.Str(table.concat(buf))) end
  return out
end

local function wrap(block, mode, kind)
  return pandoc.Div({ block }, pandoc.Attr("", { "v-" .. mode, "v-" .. kind }))
end

local tcy_filter = {
  Str = function(s) return split_tcy(s.text) end,
  -- 既にクラス指定された span（手動の縦中横など）や URL の中は触らない
  Span = function(sp)
    if sp.classes:includes("tcy") or sp.classes:includes("upright") or sp.classes:includes("sideways") then
      return sp, false
    end
  end,
  Link = function(l)
    if pandoc.utils.stringify(l.content) == l.target then return l, false end
  end,
}

local block_filter = {
  CodeBlock = function(cb) return wrap(cb, code_mode, "code") end,
  Table = function(t) return wrap(t, table_mode, "table") end,
}

function Pandoc(doc)
  local k = doc.meta.kbt
  if not k or pandoc.utils.stringify(k.writing_mode or "") ~= "vertical" then
    return nil
  end
  if k.tcy_digits then tcy_max = tonumber(pandoc.utils.stringify(k.tcy_digits)) or tcy_max end
  if k.vertical_code then code_mode = pandoc.utils.stringify(k.vertical_code) end
  if k.vertical_table then table_mode = pandoc.utils.stringify(k.vertical_table) end
  -- 表の中の数字も縦中横にするのは vertical（縦組み表）のときだけ
  doc = doc:walk(block_filter)
  local walker = {
    traverse = "topdown",
    Div = function(d)
      if (d.classes:includes("v-sideways") or d.classes:includes("v-horizontal")) then
        return d, false
      end
    end,
    Str = tcy_filter.Str,
    Span = tcy_filter.Span,
    Link = tcy_filter.Link,
    Code = function(c) return c, false end,
  }
  doc = doc:walk(walker)
  return doc
end
