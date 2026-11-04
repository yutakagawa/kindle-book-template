--[[
ruby.lua — ルビ（ふりがな）を <ruby> 要素に変換する Pandoc Lua フィルタ

書き方は 2 通り:

  1. 短縮記法（でんでんマークダウン互換）
       {漢字|かんじ}        … グループルビ（熟語全体に読み）
       {漢字|かん|じ}       … モノルビ（1 文字ずつ。親文字数と読みの数が同じとき）

  2. Pandoc の span 記法
       [漢字]{ruby="かんじ"}
]]

local function esc(s)
  return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

local function utf8_chars(s)
  local t = {}
  for _, c in utf8.codes(s) do
    t[#t + 1] = utf8.char(c)
  end
  return t
end

local function split(s, sep)
  local t = {}
  for part in (s .. sep):gmatch("(.-)" .. sep:gsub("%p", "%%%0")) do
    t[#t + 1] = part
  end
  return t
end

-- <rp>（括弧のフォールバック）は出力しない。
--   EPUB 3.3 では rp は非推奨（EPUBCheck が HTM_055 を報告する）で、
--   Kindle を含む EPUB3 リーダーはルビに対応しているため不要。
--   （ルビ非対応のリーダーでは「漢字かんじ」のように続けて表示される）
local function make_ruby(base, reading)
  local readings = split(reading, "|")
  local html = { "<ruby>" }
  local chars = utf8_chars(base)
  if #readings > 1 and #readings == #chars then
    -- モノルビ
    for i, ch in ipairs(chars) do
      html[#html + 1] = esc(ch) .. "<rt>" .. esc(readings[i]) .. "</rt>"
    end
  else
    html[#html + 1] = esc(base) .. "<rt>" .. esc(table.concat(readings, "")) .. "</rt>"
  end
  html[#html + 1] = "</ruby>"
  return pandoc.RawInline("html", table.concat(html))
end

-- Str 内の {親文字|ルビ} を展開する
local function expand_str(text)
  if not text:find("{", 1, true) then
    return nil
  end
  local out = pandoc.List()
  local pos = 1
  while true do
    local s, e, base, reading = text:find("{([^{}|]+)|([^{}]+)}", pos)
    if not s then break end
    if s > pos then out:insert(pandoc.Str(text:sub(pos, s - 1))) end
    out:insert(make_ruby(base, reading))
    pos = e + 1
  end
  if pos == 1 then return nil end
  if pos <= #text then out:insert(pandoc.Str(text:sub(pos))) end
  return out
end

local function is_html_like()
  return FORMAT:match("html") or FORMAT:match("epub")
end

-- 親文字にスペースが含まれる場合に備え、Str/Space を連結してから処理する
function Inlines(inlines)
  if not is_html_like() then return nil end
  local result = pandoc.List()
  local buf = nil
  local function flush()
    if buf then
      local expanded = expand_str(buf)
      if expanded then result:extend(expanded) else
        -- 元の Str/Space に戻す
        local first = true
        for piece in (buf .. " "):gmatch("(.-) ") do
          if not first then result:insert(pandoc.Space()) end
          if piece ~= "" then result:insert(pandoc.Str(piece)) end
          first = false
        end
      end
      buf = nil
    end
  end
  for _, el in ipairs(inlines) do
    if el.t == "Str" then
      buf = (buf or "") .. el.text
    elseif el.t == "Space" and buf then
      buf = buf .. " "
    else
      flush()
      result:insert(el)
    end
  end
  flush()
  return result
end

function Span(el)
  local reading = el.attributes["ruby"]
  if not reading or not is_html_like() then return nil end
  return make_ruby(pandoc.utils.stringify(el.content), reading)
end
