"""GitHub 上有实际影响力的编程语言列表。

用途
----
爬虫以 language + created 区间 做二维切分，
每个切片的结果数 < 1000，从而绕开 GitHub Search API 的 1000 条上限。

覆盖原则
--------
- 只保留 GitHub 上真正有项目的语言（减少无效请求）
- 不同语言之间没有交集（GitHub 每个仓库只有一个 primary language）
- 最后必须加一个 ``None`` 语言切片，捕捉 language 未设置的仓库
"""
from __future__ import annotations

# GitHub Search API 里 language 字段的标准写法（大小写敏感）
LANGUAGES: list[str] = [
    "Python",
    "JavaScript",
    "TypeScript",
    "Java",
    "Go",
    "Rust",
    "C",
    "C++",
    "C#",
    "Swift",
    "Kotlin",
    "Ruby",
    "PHP",
    "Shell",
    "Scala",
    "Dart",
    "Lua",
    "Vim script",
    "Haskell",
    "Elixir",
    "Clojure",
    "Erlang",
    "R",
    "MATLAB",
    "Jupyter Notebook",
    "HTML",
    "CSS",
    "Vue",
    "Svelte",
    "Nix",
    "Zig",
    "OCaml",
    "F#",
    "Perl",
    "Groovy",
    "PowerShell",
    "Dockerfile",
    "HCL",
    "Makefile",
    "Assembly",
    "VHDL",
    "Verilog",
    "TeX",
    "MDX",
]

# language=None 的仓库（未设置主语言），单独用空字符串占位表示
LANGUAGE_NONE_SENTINEL = "__none__"
