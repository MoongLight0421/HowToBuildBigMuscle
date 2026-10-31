# 共享技术 Skills

本仓库包含 5 个团队技术 Skill 和本地工程检查。它们位于 `.agents/skills/`，不依赖个人 Skill 目录、外部品牌技能、私人原始包或安装摘要。

| Skill | 何时使用 |
|---|---|
| [shiao-product-spec](../.agents/skills/shiao-product-spec/SKILL.md) | 需求范围、用户故事、依赖和验收 |
| [shiao-web-miniapp](../.agents/skills/shiao-web-miniapp/SKILL.md) | 管理端与 Uniapp 移动端流程、数据/View 分离与平台验证 |
| [shiao-api-data](../.agents/skills/shiao-api-data/SKILL.md) | API、实体、状态、MySQL、缓存和对象存储语义 |
| [shiao-go-backend](../.agents/skills/shiao-go-backend/SKILL.md) | Go 三层实现、对象职责与代码审查 |
| [shiao-qa-release](../.agents/skills/shiao-qa-release/SKILL.md) | 验收、安全、实际测试和发布证据 |

例如可明确请求“使用 $shiao-api-data 审查这份接口”。实际自动发现和隐式选择取决于每位成员使用的工具与配置；文件检查不证明应用已重新载入或执行了该 Skill。其他 AI 工具应按其正式配置方式读取 [AGENTS.md](../AGENTS.md)和相关 Skill，不复制某个成员的登录状态或插件缓存。

## 检查与格式

```sh
make check
```

这会执行隔离临时样例回归、[工程 harness](../engineering/harness/README.md)和 `scripts/validate_technical_skills.py`。报告保存至 `.reports/`。Skills 验证器仅使用 Python 3.9+ 标准库，不要求 Ruby、PyYAML 或原始附件。

本包 frontmatter 刻意限定为以下格式：

```yaml
---
name: shiao-product-spec
description: 将团队需求整理为范围和验收标准。
---
```

只支持两个顶层字段、各占一行的无引号纯文本，名称须与目录一致；description 以中文或英文字母开头。额外字段、重复键、注释、引号、缩进、空字段、多行值、类型标量、锚点、别名、标签、集合和其他 YAML 特殊语法均会保守拒绝。它不是完整 YAML 解析器；需要更丰富元数据时，应明确升级解析方式和测试，再修改本包格式，不能让不支持语法静默通过。

验证内容包括恰好 5 个 Skill、名称与正文、AGENTS 相对路由、包内链接存在性和不越界、无包外项目 Skill 依赖。当前 SHA-256 只标识本次文件字节，不是签名、历史来源或不可变授权基线。Markdown 链接按本包使用的内联链接格式检查，不覆盖任意 Markdown 扩展语法。脚本不验证 Skill 的判断质量、自动发现、所有外部链接可达性或运行效果。

## 技术与运行边界

规范见 [开发规范](../engineering/DEVELOPMENT_STANDARDS.md)。移动端采用 Uniapp；本次管理端实施建议为独立 Vue 3，最终框架与组件库在初始化前确认。Ant Design Pro 是候选，未据此选择 React。

工程扫描根为 `backend/`、`frontend/admin/` 和 `frontend/mobile/`。当前没有应用源码时报告明确跳过，不能认作应用合规或发布就绪。真实 Go/前端构建、MySQL/Redis 集成、状态竞争、缓存 TTL、对象存储权限与恢复必须在实际环境另验。

CI 只配置本仓库本地检查，不创建云资源、不登录账户、不部署。远程 CI 是否实际通过，以对应提交的真实运行结果为准；受保护分支的必选检查需仓库维护者另行配置。

官方参考使用 [阿里 P3C](https://github.com/alibaba/p3c)、[Go](https://go.dev/doc/)、[Uniapp](https://uniapp.dcloud.io/)及开发规范中的直接链接。本仓库不随包带入原始会议、私人 PRD/原型、运营资料、云凭据或第三方手册 PDF。

## 本地迁移验证

2026-10-31 在仓库内执行 make check，并把 18 个明确技术文件复制至不含原始资料、个人目录或 Git 历史的临时目录再次执行，均通过 30 项回归（23 项工程检查、7 项 Skills 检查）和 5/5 技能结构验证。三个应用扫描根的临时违规样例均能被检出。当前真实应用源码为空，工程检查明确跳过，发布就绪为 false。

尝试运行系统 skill-creator 的官方 quick_validate，但当前 Python 缺少 PyYAML，未成功执行；未为此安装第三方依赖。这里的标准库保守格式验证与隔离回归仅证明本包声明范围，不能当成官方完整 YAML 验证、实际 Skill 行为评估或远程 CI 成功。
