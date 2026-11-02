--[[
linebreaks.lua — 日本語の原稿中の改行で余計な空白が入らないようにする

Pandoc の east_asian_line_breaks 拡張は「改行の前後が両方とも全角文字」のときだけ
空白を消すため、「…転記する。<改行>10時に…」のように行頭が半角英数字だと空白が入ってしまう。
このフィルタは、改行の前後どちらかが全角文字（CJK・全角記号）なら空白を入れない。
英文同士の改行は通常どおり空白になる。
]]

local function is_wide(cp)
  return cp and (
    (cp >= 0x1100 and cp <= 0x11FF) or   -- ハングル字母
    (cp >= 0x2E80 and cp <= 0x9FFF) or   -- CJK 記号・かな・漢字
    (cp >= 0xA960 and cp <= 0xA97F) or
    (cp >= 0xAC00 and cp <= 0xD7FF) or   -- ハングル
    (cp >= 0xF900 and cp <= 0xFAFF) or   -- CJK 互換漢字
    (cp >= 0xFE30 and cp <= 0xFE4F) or   -- CJK 互換形
    (cp >= 0xFF00 and cp <= 0xFFEF) or   -- 全角英数・半角カナ
    (cp >= 0x20000 and cp <= 0x3FFFF)    -- CJK 拡張
  )
end

local function first_cp(el)
  local s = pandoc.utils.stringify(el)
  if s == "" then return nil end
  return utf8.codepoint(s, 1)
end

local function last_cp(el)
  local s = pandoc.utils.stringify(el)
  if s == "" then return nil end
  local last
  for _, c in utf8.codes(s) do last = c end
  return last
end

function Inlines(inlines)
  local out = pandoc.List()
  for i, el in ipairs(inlines) do
    if el.t == "SoftBreak" then
      local prev, nxt = inlines[i - 1], inlines[i + 1]
      if (prev and is_wide(last_cp(prev))) or (nxt and is_wide(first_cp(nxt))) then
        -- 何も出力しない（改行を詰める）
      else
        out:insert(el)
      end
    else
      out:insert(el)
    end
  end
  return out
end
