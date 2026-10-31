#!/usr/bin/env python3
"""Run a limited, offline engineering policy gate. / 运行有限的离线工程规范检查。"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def validate_policy(policy):
    """Reject malformed or misleading policy configuration. / 拒绝结构损坏或规则描述失真的策略。

    Args / 参数: policy is parsed JSON data / policy 为解析后的 JSON。
    Returns / 返回: None on success / 有效时无返回值。
    Raises / 错误: ValueError on unsupported schema / 不支持的结构会报错。No side effects / 无副作用。
    """
    if not isinstance(policy, dict) or not isinstance(policy.get("version"), str) or not policy["version"]:
        raise ValueError("invalid policy version")
    for key in ("source_roots", "excluded_directories", "source_extensions", "config_extensions"):
        value = policy.get(key)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
            raise ValueError("invalid policy list")
    for configured in policy["source_roots"]:
        if Path(configured).is_absolute() or ".." in Path(configured).parts:
            raise ValueError("unsafe policy root")
    if type(policy.get("maximum_file_bytes")) is not int or policy["maximum_file_bytes"] <= 0:
        raise ValueError("invalid file size limit")
    for key in ("rules", "manual_rules"):
        value = policy.get(key)
        if not isinstance(value, dict) or not value or any(not isinstance(name, str) or not isinstance(description, str) or not description for name, description in value.items()):
            raise ValueError("invalid policy rule descriptions")
    if set(policy["rules"]) != {"SEC001", "SEC002", "VIEW001", "LAYER001", "LAYER002", "SQL001", "SQL002", "DDL001", "DDL002", "DDL003", "INPUT001"}:
        raise ValueError("policy does not describe implemented rules exactly")


def add_finding(findings, rule, path, text, offset, message):
    """Append a redacted finding. / 添加不包含源码或密钥值的发现。

    Args / 参数: findings is the mutable list; rule/path identify the issue;
    text/offset locate its line; message is a fixed explanation.
    findings 为待写列表，其他参数提供规则、位置及固定说明。
    Returns / 返回: None. Side effects / 副作用: appends to findings / 写入列表。
    """
    findings.append({"rule": rule, "path": path, "line": text.count("\n", 0, offset) + 1,
                     "message": message})


def mask_comments(text, sql=False):
    """Replace comments while retaining quoted text and line positions. / 遮蔽注释并保留字符串及行号。

    Args / 参数: text is source; sql enables SQL line comments / text 为源码，sql 启用 SQL 注释。
    Returns / 返回: a same-length string / 等长文本。No side effects / 无副作用。
    This is lexical screening, not a language parser. / 此函数只做词法筛查，不是完整解析器。
    """
    chars = list(text)
    i = 0
    quote = None
    while i < len(text):
        current = text[i]
        if quote:
            if current == "\\" and quote != "`":
                i += 2
                continue
            if current == quote:
                if sql and i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if current in "\"'`":
            quote = current
            i += 1
            continue
        if text.startswith("/*!", i) and sql:
            # MySQL executable comments remain visible. / 保留 MySQL 可执行注释中的语句。
            chars[i:i + 3] = "   "
            ending = text.find("*/", i + 3)
            if ending >= 0:
                chars[ending:ending + 2] = "  "
            i += 3
            continue
        if text.startswith("/*", i):
            ending = text.find("*/", i + 2)
            ending = len(text) if ending < 0 else ending + 2
        elif text.startswith("//", i) or (sql and (text.startswith("--", i) or current == "#")):
            ending = text.find("\n", i)
            ending = len(text) if ending < 0 else ending
        else:
            i += 1
            continue
        for position in range(i, ending):
            if chars[position] != "\n":
                chars[position] = " "
        i = ending
    return "".join(chars)


def scan_secrets(path, text, findings):
    """Screen recognizable credentials without returning values. / 筛查可识别凭据且不返回凭据值。

    Args / 参数: path is relative; text is file content; findings collects issues / 路径、内容和发现列表。
    Returns / 返回: None. Side effects / 副作用: appends redacted findings / 添加脱敏发现。
    """
    patterns = [
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        r"(?im)[\"']?(?:aws_secret_access_key|secret_access_key|aws_session_token|api_key|api_secret|client_secret|password|passwd|db_password|redis_password)[\"']?\s*[:=]\s*[\"']([^\"'\r\n]+)[\"']",
    ]
    for number, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text):
            if number == 2:
                value = match.group(1).strip()
                if (not value or re.fullmatch(r"(?:<[^>]+>|\$\{[^}]+\}|\{\{[^}]+\}\}|(?:YOUR|REPLACE|CHANGE|EXAMPLE|PLACEHOLDER)[A-Z0-9_ -]*)", value, re.I)):
                    continue
            add_finding(findings, "SEC001", path, text, match.start(), "发现疑似明文凭据；值已隐藏。")
    if re.search(r"(?i)(?:^|/)[^/]*(?:credentials?|passwords?)[^/]*\.csv$", path):
        add_finding(findings, "SEC002", path, text, 0, "工程目录不应存放凭据 CSV。")


def scan_view(path, text, findings):
    """Screen Vue files for direct infrastructure access. / 筛查 Vue 视图中的基础设施直连。

    Args / 参数: path/text describe a Vue file; findings collects issues / Vue 路径、源码与发现列表。
    Returns / 返回: None. Side effects / 副作用: adds findings / 添加发现。
    """
    patterns = [
        r"\buni\s*\.\s*(?:request|uploadFile|downloadFile|connectSocket)\s*\(",
        r"\b(?:fetch|axios|XMLHttpRequest)\s*(?:\(|\.)",
        r"(?:\bfrom\s*|\brequire\s*\()\s*['\"](?:axios|mysql2?|redis|ioredis|aws-sdk|@aws-sdk/[^'\"]+|ali-oss)(?:/[^'\"]*)?['\"]",
    ]
    characters = list(text)
    for comment in re.finditer(r"<!--[\s\S]*?-->", text):
        for position in range(comment.start(), comment.end()):
            if characters[position] != "\n":
                characters[position] = " "
    cleaned = mask_comments("".join(characters))
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned):
            add_finding(findings, "VIEW001", path, text, match.start(), "View 中发现直接请求或中间件 SDK；应经独立数据层。")


def scan_go_layers(path, text, findings):
    """Check recognizable Go import dependencies. / 检查可识别的 Go 层间导入依赖。

    Args / 参数: path/text identify Go source; findings collects issues / Go 路径、源码与发现列表。
    Returns / 返回: None. Side effects / 副作用: adds findings / 添加发现。
    """
    layers = [part for part in Path(path).parts if part in {"controller", "service", "dao"}]
    if not layers:
        return
    layer = layers[-1]
    forbidden = {"controller": {"dao"}, "service": {"controller"}, "dao": {"service", "controller"}}
    cleaned = mask_comments(text)
    imports = re.finditer(r'\bimport\s*(?:\((?P<block>[\s\S]*?)\)|(?:[\w.]+\s+)?(?P<single>"[^"\n]+"))', cleaned)
    for declaration in imports:
        group = "block" if declaration.group("block") is not None else "single"
        for imported in re.finditer(r'"([^"\n]+)"', declaration.group(group)):
            target = imported.group(1)
            offset = declaration.start(group) + imported.start()
            if set(target.split("/")) & forbidden[layer]:
                add_finding(findings, "LAYER001", path, text, offset, "发现 controller/service/dao 禁止的导入方向。")
            if layer == "controller" and re.match(r"^(?:database/sql(?:/|$)|gorm\.io/|github\.com/(?:go-sql-driver/mysql|redis/|go-redis/|aws/aws-sdk-go|aliyun/aliyun-oss))", target):
                add_finding(findings, "LAYER002", path, text, offset, "Controller 直接导入持久化、缓存或对象存储 SDK。")


def scan_sql_operations(path, text, findings, sql_file=False):
    """Screen explicit SQL lock and deletion syntax. / 筛查显式 SQL 锁及物理删除语法。

    Args / 参数: path/text identify source; sql_file enables SQL comments; findings collects issues.
    path/text 为源码，sql_file 启用 SQL 注释，findings 收集发现。
    Returns / 返回: None. Side effects / 副作用: adds findings / 添加发现。
    """
    cleaned = mask_comments(text, sql=sql_file)
    if not sql_file:
        # Preserve offsets while screening common static SQL encodings. / 等长转换常见静态 SQL 写法。
        characters = list(cleaned)
        for escaped in re.finditer(r"\\[nrt]", cleaned):
            characters[escaped.start():escaped.end()] = "  "
        for comment in re.finditer(r"/\*(?!\!)[\s\S]*?\*/", cleaned):
            for position in range(comment.start(), comment.end()):
                if characters[position] != "\n":
                    characters[position] = " "
        cleaned = "".join(characters)
    rules = {
        "SQL001": (r"\b(?:FOR\s+(?:UPDATE|SHARE)|LOCK\s+IN\s+SHARE\s+MODE|(?:UN)?LOCK\s+TABLES|(?:GET_LOCK|RELEASE_LOCK|RELEASE_ALL_LOCKS|IS_FREE_LOCK|IS_USED_LOCK)\s*\()", "发现显式数据库业务锁语法；请改用适用的乐观并发控制。"),
        "SQL002": (r"\b(?:DELETE\s+(?:FROM\b|[A-Za-z_`][\w`.,\s]*?\s+FROM\b)|TRUNCATE\s+(?:TABLE\s+)?[A-Za-z_`]|ON\s+DELETE\s+CASCADE\b)", "发现业务数据物理删除语法；应使用逻辑删除。"),
    }
    for rule, (pattern, message) in rules.items():
        for match in re.finditer(pattern, cleaned, re.I):
            add_finding(findings, rule, path, text, match.start(), message)


def matching_parenthesis(text, start):
    """Find a closing parenthesis while respecting strings. / 在跳过字符串的情况下查找配对右括号。

    Args / 参数: text is SQL; start points at '(' / SQL 文本和左括号位置。
    Returns / 返回: closing index, or -1 for unsupported/unclosed text / 右括号位置，未闭合时为 -1。
    No side effects / 无副作用。
    """
    depth = 0
    quote = None
    i = start
    while i < len(text):
        current = text[i]
        if quote:
            if current == "\\":
                i += 2
                continue
            if current == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif current in "\"'`":
            quote = current
        elif current == "(":
            depth += 1
        elif current == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_definitions(text):
    """Split top-level CREATE TABLE definitions. / 按顶层逗号分割建表定义。

    Args / 参数: text is a table body / text 为表体。
    Returns / 返回: list of (offset, definition) / 偏移与定义的列表。No side effects / 无副作用。
    """
    result = []
    start = 0
    i = 0
    quote = None
    while i < len(text):
        current = text[i]
        if quote:
            if current == "\\":
                i += 2
                continue
            if current == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif current in "\"'`":
            quote = current
        elif current == "(":
            ending = matching_parenthesis(text, i)
            if ending < 0:
                return []
            i = ending
        elif current == ",":
            result.append((start, text[start:i]))
            start = i + 1
        i += 1
    result.append((start, text[start:]))
    return result


def index_columns(definition):
    """Read simple index column names. / 读取简单索引字段名。

    Args / 参数: definition starts with KEY/INDEX/PRIMARY KEY / 索引定义。
    Returns / 返回: column names or [] when expressions are unsupported / 字段名列表，不支持的表达式返回空。
    No side effects / 无副作用。
    """
    start = definition.find("(")
    end = matching_parenthesis(definition, start) if start >= 0 else -1
    if end < 0:
        return []
    names = []
    for _, part in split_definitions(definition[start + 1:end]):
        match = re.fullmatch(r"\s*`?([A-Za-z_]\w*)`?(?:\s*\(\s*\d+\s*\))?(?:\s+(?:ASC|DESC))?\s*", part, re.I)
        if not match:
            return []
        names.append(match.group(1).lower())
    return names


def scan_ddl(path, text, findings):
    """Check basic CREATE TABLE fields and query indexes. / 检查基础建表字段及查询组合索引。

    Args / 参数: path/text identify a SQL file; findings collects issues / SQL 路径、内容与发现列表。
    Returns / 返回: number of supported table declarations / 支持的建表语句数。
    Side effects / 副作用: adds findings / 添加发现。ALTER/generated SQL needs manual review / ALTER 等需人工审查。
    """
    cleaned = mask_comments(text, sql=True)
    tables = 0
    required = {"id", "created_by", "created_at", "updated_by", "updated_at", "is_deleted"}
    pattern = r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?[A-Za-z_]\w*`?\s*\.\s*)?`?[A-Za-z_]\w*`?\s*\("
    for table in re.finditer(pattern, cleaned, re.I):
        start = table.end() - 1
        end = matching_parenthesis(cleaned, start)
        if end < 0:
            add_finding(findings, "DDL001", path, text, table.start(), "建表定义未闭合，无法完成基础检查。")
            continue
        tables += 1
        definitions = split_definitions(cleaned[start + 1:end])
        columns = {}
        primary = []
        for offset, definition in definitions:
            stripped = definition.strip()
            prefix = re.match(r"`?([A-Za-z_]\w*)`?\s+", stripped)
            if prefix and prefix.group(1).lower() not in {"constraint", "primary", "unique", "key", "index", "foreign", "check", "fulltext", "spatial"}:
                name = prefix.group(1).lower()
                columns[name] = stripped
                if re.search(r"\bPRIMARY\s+KEY\b", stripped, re.I):
                    primary = [name]
            if re.match(r"(?:CONSTRAINT\s+`?[A-Za-z_]\w*`?\s+)?PRIMARY\s+KEY\b", stripped, re.I):
                primary = index_columns(stripped)
            if re.match(r"(?:KEY|INDEX)\b", stripped, re.I):
                index = index_columns(stripped)
                if len(index) > 1 and index[0] != "is_deleted":
                    add_finding(findings, "DDL003", path, text, start + 1 + offset, "非唯一查询组合索引必须以 is_deleted 开头。")
        missing = sorted(required - set(columns))
        if missing:
            add_finding(findings, "DDL001", path, text, table.start(), "业务表缺少必需字段：" + ", ".join(missing))
        if primary != ["id"]:
            add_finding(findings, "DDL002", path, text, table.start(), "业务表须使用独立 id 主键。")
        deleted = columns.get("is_deleted", "")
        if deleted and (not re.search(r"\bNOT\s+NULL\b", deleted, re.I) or not re.search(r"\bDEFAULT\s+(?:0(?![\w.])|'0'|FALSE\b|b'0')", deleted, re.I)):
            add_finding(findings, "DDL002", path, text, table.start(), "is_deleted 必须非空且默认未删除（0）。")
    for index in re.finditer(r"\bCREATE\s+(?:INDEX|KEY)\s+`?[A-Za-z_]\w*`?\s+ON\s+(?:`?[A-Za-z_]\w*`?\.)?`?[A-Za-z_]\w*`?\s*\(", cleaned, re.I):
        ending = matching_parenthesis(cleaned, index.end() - 1)
        names = index_columns(cleaned[index.start():ending + 1]) if ending >= 0 else []
        if len(names) > 1 and names[0] != "is_deleted":
            add_finding(findings, "DDL003", path, text, index.start(), "非唯一查询组合索引必须以 is_deleted 开头。")
    return tables


def collect_files(root, policy):
    """Collect in-scope engineering text files without following symlinks. / 收集范围内文本且不跟随符号链接。

    Args / 参数: root is project directory; policy defines roots/extensions/exclusions / 项目根目录与策略。
    Returns / 返回: sorted Path list / 排序后的文件列表。
    Raises / 错误: ValueError for unsafe configured roots / 不安全根目录会报错。Reads metadata / 读取元数据。
    """
    paths = set()
    excluded = set(policy["excluded_directories"])
    extensions = set(policy["source_extensions"] + policy["config_extensions"])
    for configured in policy["source_roots"]:
        source = root / configured
        if not source.resolve().is_relative_to(root.resolve()):
            raise ValueError("source root escapes the project")
        if not source.exists():
            continue
        for path in source.rglob("*"):
            relative = path.relative_to(root)
            if any(part in excluded for part in relative.parts) or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root)):
                continue
            if path.is_file() and (path.suffix.lower() in extensions or path.name.startswith(".env") or (path.suffix.lower() == ".csv" and re.search(r"(?i)credential|password", path.name))):
                paths.add(path)
    return sorted(paths)


def run_checks(root, policy):
    """Run limited policy screening and build a redacted report. / 执行有限筛查并生成脱敏报告。

    Args / 参数: root is project path; policy is validated policy data / 项目路径及策略字典。
    Returns / 返回: JSON-serializable report / 可序列化报告。
    Side effects / 副作用: reads in-scope files only / 仅读取范围内文件。不联网、不运行应用。
    """
    validate_policy(policy)
    findings = []
    files = collect_files(root, policy)
    counts = {"source": 0, "go": 0, "vue": 0, "sql": 0, "tables": 0, "configuration": 0}
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.stat().st_size > policy["maximum_file_bytes"]:
            add_finding(findings, "INPUT001", relative, "", 0, "文件超过扫描上限；必须拆分或调整已审查策略后复验。")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError):
            add_finding(findings, "INPUT001", relative, "", 0, "文件无法按 UTF-8 读取；未完成扫描。")
            continue
        suffix = path.suffix.lower()
        if suffix in policy["source_extensions"]:
            counts["source"] += 1
        else:
            counts["configuration"] += 1
        scan_secrets(relative, text, findings)
        if suffix == ".vue":
            counts["vue"] += 1
            scan_view(relative, text, findings)
        if suffix == ".go":
            counts["go"] += 1
            scan_go_layers(relative, text, findings)
        if suffix in policy["source_extensions"]:
            scan_sql_operations(relative, text, findings, sql_file=(suffix == ".sql"))
        if suffix == ".sql":
            counts["sql"] += 1
            counts["tables"] += scan_ddl(relative, text, findings)
    checks = [
        {"check": "credential_patterns", "status": "completed" if files else "skipped", "files": len(files)},
        {"check": "vue_view_boundary", "status": "completed" if counts["vue"] else "skipped", "files": counts["vue"]},
        {"check": "go_import_layers", "status": "completed" if counts["go"] else "skipped", "files": counts["go"]},
        {"check": "sql_lock_and_deletion_patterns", "status": "completed" if counts["source"] else "skipped", "files": counts["source"]},
        {"check": "create_table_basics", "status": "completed" if counts["tables"] else "skipped", "tables": counts["tables"]},
        {"check": "go_compile_vet_test_race", "status": ("not_run" if shutil.which("go") else "blocked_missing_toolchain") if counts["go"] else "skipped"},
        {"check": "frontend_build_and_platform_tests", "status": "not_run" if counts["vue"] else "skipped"},
        {"check": "mysql_redis_object_storage_integration", "status": "not_run" if counts["source"] else "skipped"},
    ]
    return {
        "policy_version": policy["version"],
        "status": "failed" if findings else ("passed_limited_static_checks" if counts["source"] else "skipped_no_application_source"),
        "release_ready": False,
        "counts": counts,
        "findings": findings,
        "checks": checks,
        "manual_reviews": [{"rule": key, "requirement": value, "status": "pending" if counts["source"] else "not_applicable_yet"} for key, value in policy["manual_rules"].items()],
        "limitations": ["文本模式检查不是完整 Go/JS/SQL 解析，可能误报或漏报；必须审查全部人工项。", "未运行应用编译、单元测试、数据库、Redis、对象存储、管理端构建或移动端打包；静态无发现不代表完整合规。", "扫描仅覆盖策略规定的工程根目录，排除第三方、harness、资料和交付文件；新源码位置必须加入策略。"],
    }


def main(argv=None):
    """Parse CLI options and write a redacted report. / 解析命令并写入脱敏报告。

    Args / 参数: argv optionally overrides command arguments / 可选命令参数列表。
    Returns / 返回: 0 for no static finding (including skipped), 1 for findings, 2 for input errors.
    0 表示未检出静态问题（包含无源码），1 表示发现问题，2 表示输入错误。
    Side effects / 副作用: reads files, prints JSON and optionally writes --json / 读取文件、输出及按需写报告。
    """
    parser = argparse.ArgumentParser(description="Offline limited engineering policy gate / 离线工程规范筛查")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy", type=Path, default=Path(__file__).resolve().parents[1] / "engineering/harness/policy.json")
    parser.add_argument("--json", type=Path, dest="report_path")
    args = parser.parse_args(argv)
    try:
        if not args.root.is_dir():
            raise ValueError("project root is not a directory")
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        report = run_checks(args.root.resolve(), policy)
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report_path:
            args.report_path.parent.mkdir(parents=True, exist_ok=True)
            args.report_path.write_text(output, encoding="utf-8")
        print(output, end="")
        return 1 if report["findings"] else 0
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"status": "input_error", "message": "输入、策略或报告路径不可用；未完成检查。"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
