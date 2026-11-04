-- 画像の参照先を、ビルド時に最適化した画像（scripts/images.py が作ったもの）に差し替える。
-- 対応表は build.py が metadata の kbt.images（元画像の相対パス → 最適化版の絶対パス）で渡す。
-- 原稿の書き方は変わらない: ![説明](images/foo.png) は images/foo.png の最適化版になる。

local map = {}

local function normalize(path)
  path = path:gsub("\\", "/"):gsub("^%./", "")
  -- 「a/../b」「a/./b」を畳む
  local parts = {}
  for part in path:gmatch("[^/]+") do
    if part == ".." and #parts > 0 and parts[#parts] ~= ".." then
      table.remove(parts)
    elseif part ~= "." then
      table.insert(parts, part)
    end
  end
  return table.concat(parts, "/")
end

local function unescape(s)
  return (s:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end))
end

function Meta(meta)
  local kbt = meta.kbt
  if kbt and kbt.images then
    for k, v in pairs(kbt.images) do
      map[normalize(k)] = pandoc.utils.stringify(v)
    end
  end
end

local function lookup(src)
  if src:match("^%a[%w+.-]*:") then -- URL（http:, data: など）は対象外
    return nil
  end
  local path = normalize(unescape(src))
  -- build.py の --resource-path（本のディレクトリ → images/）と同じ順に探す
  return map[path] or map["images/" .. path]
end

function Image(img)
  local new = lookup(img.src)
  if new then
    img.src = new
    return img
  end
end

return {
  { Meta = Meta },
  { Image = Image },
}
