# 本地技术约束检查

本工具使用 Python 3.9+ 标准库，离线筛查 [开发规范](../DEVELOPMENT_STANDARDS.md)中可识别的文本模式。无需 Ruby、PyYAML 或原始附件，所有依赖都在本仓库。

```sh
make check
```

入口执行临时合成工程回归、工程扫描、5 个技术 Skill 的格式与本地链接验证。报告写入 `.reports/`；检查实现于 `scripts/engineering_harness.py`，策略为本目录 `policy.json`。单独使用：

```sh
python3 scripts/engineering_harness.py --json .reports/harness-report.json
python3 scripts/validate_technical_skills.py --json .reports/technical-skills.json
```

扫描根目录为 `backend/`、`frontend/admin/`、`frontend/mobile/`。实际代码目录变化时先更新策略和测试。`--root` 可指定项目副本，`--policy` 可指定已审查策略；默认策略以脚本所在仓库定位，`--json` 相对于当前工作目录。

## 机器范围与边界

| 规则 | 已实现的有限检查 | 需另验的内容 |
|---|---|---|
| SEC001、SEC002 | 常见 AWS key ID/私钥头、特定字段引号内明文凭据、工程凭据 CSV | 拆分/编码/无引号秘密、自定义字段、扫描根外文件；报告不回显命中值 |
| VIEW001 | `.vue` 中直接 uni.request/upload/download/connectSocket、fetch/axios/XMLHttpRequest 和选定 SDK 导入 | 间接别名、全部转换逻辑、非 Vue 的 View；React 选型未确认也未实现专属检查 |
| LAYER001、LAYER002 | Go 路径段 controller/service/dao 的禁止导入方向和 Controller 直接持久化 SDK | 完整调用图、依赖注入和其他名称的层 |
| SQL001、SQL002 | 常见显式锁/命名锁、DELETE/TRUNCATE/ON DELETE CASCADE，包含源码字符串中的 SQL | 动态构造、ORM 方法和完整语言求值；正常事务与引擎内部锁没有被禁止 |
| DDL001、DDL002 | `.sql` 常规 CREATE TABLE 的 id 独立主键、四审计字段、非空且默认 0 的 is_deleted | 范式、实际字段类型、写入审计、version、数据库执行 |
| DDL003 | 常规表内 KEY/INDEX 和 CREATE INDEX 的非唯一组合索引首列 is_deleted | 主键/UNIQUE/表达式/ALTER 的语义及软删历史唯一性 |
| INPUT001 | 超过 2 MiB 或无法读取为 UTF-8 的范围内文件阻断 | 不把未读文件当作已验证 |

常见代码注释、Vue HTML 注释和 SQL 文件注释保行遮蔽；MySQL 可执行注释保留。源码字符串中的反斜线 n/r/t 与内部 SQL 块注释做等长正规化；不完整解码十六进制/Unicode，不求值拼接或模板。URL 字符串内的 `//` 不会被当作源码注释删除。说明性字符串也可能触发，因此这不是完整语言解析器，误报与漏报须审查。

排除目录段包括 harness、docs、data、source、outputs、vendor、node_modules、dist、build、unpackage、.git、__pycache__、.reports、.venv；不跟随符号链接。具体扩展名和所有排除项以策略为准。应用源码不能放入排除目录来规避检查；本工具不是全仓库或所有 Git 历史的密钥扫描器。

## 结果和门禁

工程扫描退出码 0 表示未发现已实现的文本规则问题，包括无源码跳过；1 表示发现问题；2 表示输入、策略或读写错误。读取报告中的状态、计数、人工项和未运行检查，不能只看退出码。无源码为 `skipped_no_application_source`，`release_ready` 保持 false。

双语注释准确性、完整架构、数据/View 职责、范式/冗余、普通查询软删、乐观并发、全部 Redis TTL 路径与穿透防护、对象存储版本/权限保留为人工项。Go 工具缺席且存在 Go 源码时报告 blocked_missing_toolchain；工具存在也不代表已执行。真实 Go/管理端/Uniapp 编译、测试与 MySQL/Redis/对象存储集成必须分别运行并记录。

CI 只执行本仓库可移植检查，不连接账户、不部署、不安装应用依赖。提交后是否已触发、通过或设为受保护分支的必选检查，以真实远程结果为准。
