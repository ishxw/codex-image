# gen-images

给 Claude Code 用的图片生成 / 改图 skill，适用于通过 CLIProxyAPI 调用 `gpt-image-2` 的场景。

## 功能

- 支持文生图
- 支持改图 / 编辑图片
- 支持自动触发
- 支持手动使用 `/gen-images ...`
- 自动读取 Agent 当前用户配置中的 API Base URL 和 Token/KEY
- 自动将生成结果保存到当前工作目录下的 `./gen-images/`

## 使用前提

### 1. Python 环境

本 skill 通过 Python 脚本执行实际接口请求，因此本机需要可用的 Python 环境。

建议确认：

```bash
py --version
```

若无py环境可安装：
```bash
https://www.python.org/ftp/python/3.11.1/python-3.11.1-amd64.exe
```

### 2. Agent 配置

本 skill 会从下面的文件中读取当前用户配置：

```text
~/.claude/settings.json
```
或
```text
~/.codex/settings.json
```

需要存在以下字段：

- `env.ANTHROPIC_BASE_URL`
- `env.ANTHROPIC_AUTH_TOKEN`
或
- `env.OPENAI_BASE_URL`
- `env.OPENAI_API_KEY`

### 3. 后端接口支持

反代链路需要支持：

- `POST /v1/images/generations`
- `POST /v1/images/edits`

## 目录结构

```text
gen-images/
├── SKILL.md
├── README.md
├── scripts/
│   └── gen_images.py
└── references/
    └── fields.md
```

## 安装方法

将整个 `gen-images` 目录复制到 Agent 工具的用户级 skills 目录：

```text
~/.claude/skills/
```
或
```text
~/.codex/skills/
```
最终路径应为：

```text
~/.claude/skills/gen-images/SKILL.md
~/.claude/skills/gen-images/README.md
~/.claude/skills/gen-images/scripts/gen_images.py
~/.claude/skills/gen-images/references/fields.md
```

Windows 下通常对应：

```text
C:\Users\<用户名>\.claude\skills\gen-images\
```
或
```text
C:\Users\<用户名>\.codex\skills\gen-images\
```
复制后重启 Agent，或执行插件 / skill 重载。

## 使用方式

### 手动调用

```text
/gen-images 生成一张透明背景的猫咪头像，1024x1024，png
```

```text
/gen-images 把 ./input.png 改成水彩风，保留主体，输出 webp
```

### 自动触发

例如：

```text
使用 gpt-image-2 生成一张透明背景的猫咪头像
```

## 支持的图片来源

改图模式支持：

- 本地文件路径
- 图片 URL
- data URL

如果缺少图片来源，skill 会提示用户补充：

1. 本地路径
2. 图片 URL / data URL

## 支持的 size 规则

当前规则如下：

- `1024x1024`（`1:1`）
- `1024x1536`（`3:4`）
- `1536x1024`（`4:3`）
- `2048x2048`（`1:1`）
- `3840x2160`（`16:9`）
- `2160x3840`（`9:16`）
- `auto`

支持识别这些写法：

```text
1:1
3:4
4:3
16:9
9:16
1024x1024
1024x1536
1536x1024
2048x2048
3840x2160
2160x3840
auto
```

说明：

- `2160x3840`
- `3840x2160`

但这两个值不等同于 OpenAI 官方公开文档中的标准 size 枚举，属于当前链路下的实测兼容尺寸。

## 常见自然语言映射

例如：

- `高清` -> `quality=high`
- `透明背景` -> `background=transparent`
- `9:16` -> `size=2160x3840`
- `16:9` -> `size=3840x2160`
- `png/webp/jpg/jpeg` -> `output_format`
- `生成3张` -> `n=3`

更完整规则见：

- `references/fields.md`

## 超时规则

Bash 调用 `scripts/gen_images.py` 时，timeout 按图片尺寸自动设置。

统一规则以 `references/fields.md` 中的 `timeout 规则` 为准：
- 总像素量 `>= 8000000` 的 4k 级尺寸使用 15 分钟
- 其余情况使用 10 分钟
- `auto`、缺少 `size`、或无法解析时，按非 4k 处理

## 输出行为

默认输出目录：

```text
./gen-images/
```

成功时返回类似：

```text
图片已生成, 图片路径: C:\Users\xxx\gen-images\20260424-003204-01.png
实际使用的关键参数: model=gpt-image-2, size=2160x3840, quality=high, output_format=png, n=1
```

失败时返回类似：

```text
生成失败: 缺少 prompt
```

## 注意事项

1. 本 skill 依赖 Python 环境
2. 本 skill 默认从 `~/.claude/settings.json` 读取 API 配置
3. `2160x3840` / `3840x2160` 为当前链路实测可用，不保证所有后端一致支持
4. 如果复杂长提示词在超大尺寸下偶发失败，建议先做最小提示词对照测试

## 相关文件

- `SKILL.md`：skill 主定义与触发规则
- `scripts/gen_images.py`：实际图片接口调用脚本
- `references/fields.md`：字段、映射与交互规则
