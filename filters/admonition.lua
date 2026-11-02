--[[
admonition.lua — 注意書きなどの囲み（Pandoc の fenced div）

  ::: note
  本文
  :::

  ::: {.warning title="独自の見出し"}
  本文
  :::

種類: note（メモ） / tip（ヒント） / important（重要） / warning（注意） / caution（警告） / column（コラム）
title 属性を省略すると下の既定見出しが付く。title="" で見出しなし。
]]

local titles = {
  note = "メモ",
  tip = "ヒント",
  important = "重要",
  warning = "注意",
  caution = "警告",
  column = "コラム",
}

function Div(div)
  for _, cls in ipairs(div.classes) do
    local default = titles[cls]
    if default then
      local title = div.attributes["title"] or default
      div.attributes["title"] = nil
      if not div.classes:includes("admonition") then
        div.classes:insert(1, "admonition")
      end
      if title ~= "" then
        local inl = pandoc.utils.blocks_to_inlines(pandoc.read(title, "markdown").blocks)
        div.content:insert(1, pandoc.Div({ pandoc.Plain(inl) }, pandoc.Attr("", { "admonition-title" })))
      end
      return div
    end
  end
  return nil
end
