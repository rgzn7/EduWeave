# 覆盖报告视觉素材

这些素材用于复刻“浅色高级审阅件 + 深色闭环分析核心”的覆盖报告方向。

## 文件

- `coverage-flow-ribbon-bg.svg`：深色闭环面板背景与无文字丝带底图。前端应在其上叠加节点、图标、数字、百分比和断点提示。
- `node-halo-mint.svg`：覆盖充分节点光环。
- `node-halo-amber.svg`：覆盖不足节点光环。
- `node-halo-coral.svg`：覆盖薄弱/关键缺口节点光环。

## 使用建议

- 丝带底图可以作为 `<img>` 或 `background-image` 使用，按容器宽度拉伸。
- 节点、图标、数据文字不要写进底图，保持动态渲染。
- 图标优先使用 `lucide-react`，如 `BookOpen`、`FileText`、`ClipboardList`、`Presentation`、`SquarePen`、`Target`。
- 若要进一步提升质感，节点光环也可以不用图片，直接用 CSS 径向渐变和边框复刻。
