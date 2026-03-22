<![CDATA[# 📊 Day-Paper — 商业综合体经营日报自动化引擎

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue?logo=python" />
  <img src="https://img.shields.io/badge/ECharts-5.4-blueviolet?logo=apacheecharts" />
  <img src="https://img.shields.io/badge/Jinja2-Template-green" />
  <img src="https://img.shields.io/badge/Feishu-Bot-orange?logo=bytedance" />
  <img src="https://img.shields.io/badge/License-MIT-yellow" />
</p>

> 🔥 一套 **零前端框架依赖**、**纯 Python 驱动** 的商业综合体经营日报自动化解决方案。  
> 从数据拉取 → 多维度计算 → 渲染精美长图 → 推送到飞书群，全流程自动化，开箱即用。

---

## 🎯 项目定位

Day-Paper 是面向**商业综合体**（购物中心、万达广场等）运营团队的经营数据日报自动化工具。

**核心价值：** 将每天需要人工耗费 30-60 分钟手动整理的经营简报，缩减为全自动 15 秒完成，并定时推送到飞书群，让管理层随时掌握经营动态。

---

## ✨ 功能亮点

### 📋 数据表格
- **10 行 × 27 列**超大数据矩阵，覆盖所有核心经营指标
- 自动计算**日环比、周环比、年同比**
- 自动计算**月累计、月日均、月环比、月同比**
- 自动计算**年累计、年日均、周末日均、平日日均**
- 正负增长**红绿高亮**，一目了然

### 📈 可视化图表（共 12 张）
- 广场客流 / 进店客流趋势图（柱+线混合）
- 车场收入 / 车流经营趋势图
- 广场客流 / 车流 / 超市 / 影院 / 商户 / 销售 **同比趋势折线图**（6 张）
- 广场客流 / 车流 / 进店客流 / 销售 **月均年度对比柱状图**（4 张）

### 🤖 自动化推送
- 飞书群机器人自动推送文字 + 图片消息
- 支持多时间点定时执行
- 长图一键截取，无需浏览器

### 🔧 高度可配置
- 所有参数外置到 `config.ini`，零代码修改即可适配新项目
- 字段映射机制，换数据源只改一个字典
- 颜色、字体、边框等视觉元素全部可配置

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────┐
│                    config.ini                        │
│              (全局配置中心)                            │
└──────────┬──────────────────────────────┬────────────┘
           │                              │
           ▼                              ▼
┌──────────────────┐          ┌───────────────────────┐
│   数据层 (API)    │          │  可视化层 (Template)    │
│  · 客流 API      │          │  · Jinja2 模板渲染     │
│  · 车流 API      │          │  · ECharts 图表        │
│  · 天气 API      │          │  · CSS 变量系统        │
│  · CSV 历史融合   │          │  · 条件着色            │
└────────┬─────────┘          └───────────┬───────────┘
         │                                │
         ▼                                ▼
┌──────────────────────────────────────────────────────┐
│              ReportEngine (计算引擎)                   │
│  · 区间聚合查询 (get_stats)                            │
│  · 单日值查询   (get_val_by_date)                      │
│  · 多维度行构建 (build_row)                            │
│  · 同比/环比/日均 全自动计算                             │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│              输出 & 推送                               │
│  · Html2Image 截图为 PNG 长图                          │
│  · FeishuBot 自动推送至飞书群                           │
└──────────────────────────────────────────────────────┘
```

---

## 📦 快速开始

### 1. 安装依赖

```bash
pip install requests pandas schedule jinja2 html2image requests_toolbelt
```

### 2. 配置 `config.ini`

```ini
[API_CONFIG]
flow_api_url = 你的客流API地址
car_api_url = 你的车流API地址
weather_api_url = https://restapi.amap.com/v3/weather/weatherInfo?city=城市编码&key=你的高德KEY&extensions=all

[REPORT_CONFIG]
title_prefix = 你的广场名称
target_date = yesterday

[FEISHU_CONFIG]
enable_feishu = true
app_id = 你的飞书AppID
app_secret = 你的飞书AppSecret
webhook_url = 你的飞书群Webhook
```

### 3. 适配数据字段

修改 `run.py` 中的 `FIELD_MAP`，使其对应你的 API 返回字段：

```python
FIELD_MAP = {
    "flow_date": "你的日期字段名",
    "flow_total": "你的总客流字段名",
    "flow_store": "你的进店客流字段名",
    # ...
}
```

### 4. 运行

```bash
python run.py
```

---

## 📂 项目结构

```
day-paper/
├── run.py                    # 主程序（数据引擎 + 飞书推送 + 定时调度）
├── dynamic_template.html     # Jinja2 HTML 模板（含 ECharts 图表配置）
├── config.ini                # 全局配置文件（示例模板）
├── README.md                 # 项目说明文档
├── day-paper复盘资料.md       # 深度技术复盘与知识沉淀
├── .gitignore                # Git 忽略规则
├── car_history.csv           # [自动生成] 车流历史数据本地缓存
└── weather_history.json      # [自动生成] 天气数据本地缓存
```

---

## 🔑 核心设计理念

### 1. 配置驱动 (Configuration-Driven)
所有业务参数（标题、颜色、API 地址、时间点）全部外置到 `config.ini`，换一个新广场只需修改配置文件，无需改动代码逻辑。

### 2. 字段映射 (Field Mapping)
通过 `FIELD_MAP` 字典将业务语义和 API 原始字段名解耦。面对不同数据源，只需修改映射关系，引擎逻辑完全复用。

### 3. 历史融合 (History Fusion)
API 往往只返回近期数据，Day-Paper 使用本地 CSV 自动融合机制，每次运行增量同步，持续积累历史数据，支撑年度分析。

### 4. 模板化渲染 (Template Rendering)
使用 Jinja2 将数据与 HTML 视图完全分离。同一套计算引擎可以对接不同风格的模板，实现报表皮肤的自由切换。

---

## 📊 报表展示

报表包含以下内容模块（从上到下）：

| 序号 | 模块 | 说明 |
|------|------|------|
| 1 | 标题栏 | 广场名称 + 日期 + 星期 |
| 2 | 天气栏 | 日间/夜间温度、天气、风力 |
| 3 | 数据表格 | 10行 × 27列的核心经营指标矩阵 |
| 4 | 趋势图 ×2 | 广场客流+进店客流、车场收入+车流 |
| 5 | 同比折线 ×6 | 各维度同比趋势 (%) |
| 6 | 月均柱状 ×4 | 去年 vs 今年 月均日均值对比 |
| 7 | 落款 | "day-paper 资料" + 生成时间戳 |

---

## ⚙️ 定时任务

```ini
[SCHEDULE_CONFIG]
enable_schedule = true
daily_times = 07:50, 08:30
```

设置后程序将常驻运行，到达指定时间自动执行报表生成与飞书推送。

---

## 🛡️ 注意事项

1. **敏感信息**：`config.ini` 中包含飞书凭证，请勿公开上传。使用时请创建自己的配置文件。
2. **Chrome 依赖**：`html2image` 底层依赖 Chromium，首次运行可能需要下载。
3. **编码问题**：所有文件务必保存为 `UTF-8` 编码。
4. **图片高度**：新增图表后需在 `config.ini` 中同步增大 `height`（每行约 +550px）。

---

## 📜 License

MIT License — 自由使用、修改和分发。

---

## 🙏 致谢

- [ECharts](https://echarts.apache.org/) — Apache 开源可视化库
- [Jinja2](https://jinja.palletsprojects.com/) — Python 模板引擎
- [html2image](https://github.com/vgalin/html2image) — HTML 截图工具
- [高德地图 API](https://lbs.amap.com/) — 天气数据服务
]]>
