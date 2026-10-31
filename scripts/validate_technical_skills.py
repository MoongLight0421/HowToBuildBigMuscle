#!/usr/bin/env python3
"""Validate this portable Skill bundle. / 验证本可移植技术技能包。"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


EXPECTED_SKILLS = (
    "shiao-product-spec", "shiao-go-backend", "shiao-api-data",
    "shiao-web-miniapp", "shiao-qa-release",
)


def parse_frontmatter(text):
    """Parse the deliberately restricted two-field format. / 解析刻意受限的双字段格式。

    Args / 参数: text is UTF-8 Skill text / text 为技能文本。
    Returns / 返回: metadata and Markdown body / 元数据及正文。
    Raises / 错误: ValueError for unsupported syntax / 不支持的语法报错。No effects / 无副作用。
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("缺少开头 frontmatter 分隔符。")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("缺少结尾 frontmatter 分隔符。") from None
    if end != 3:
        raise ValueError("仅支持 name 和 description 两个单行字段。")
    metadata = {}
    for line in lines[1:end]:
        matched = re.fullmatch(r"(name|description): ([^\r\n]+)", line)
        if not matched or matched.group(1) in metadata:
            raise ValueError("不支持的字段、缩进、重复键或标量格式。")
        key, value = matched.groups()
        if value != value.strip() or any(character in value for character in "\t:#[]{}&*!|>'\""):
            raise ValueError("仅支持无引号、无注释和无 YAML 特殊语法的单行纯文本。")
        if re.fullmatch(r"(?:null|~|true|false|yes|no|on|off|y|n|[-+]?\d+(?:\.\d+)?|\.inf|\.nan|\d{4}-\d{2}-\d{2})", value, re.I):
            raise ValueError("不支持 YAML 类型标量。")
        if key == "description" and not re.match(r"[A-Za-z\u3400-\u9fff]", value):
            raise ValueError("本包 description 必须以中文或英文字母开头。")
        metadata[key] = value
    if set(metadata) != {"name", "description"}:
        raise ValueError("必须且只能包含 name 与 description。")
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", metadata["name"]) or len(metadata["name"]) > 64:
        raise ValueError("技能名称必须为不超过 64 字符的小写字母、数字与连字符。")
    if len(metadata["description"]) > 1024:
        raise ValueError("description 超过本包上限。")
    body = "\n".join(lines[end + 1:]).strip()
    if not body:
        raise ValueError("技能正文不能为空。")
    return metadata, body


def validate_links(root, path, body):
    """Check local Skill references remain inside this repository. / 检查本地技能引用留在仓库内。

    Args / 参数: root is repository; path/body identify Skill / 仓库路径、技能文件与正文。
    Returns / 返回: fixed error messages, without source values / 不带源码值的固定错误列表。
    Effects / 副作用: reads file metadata only / 仅读文件元数据。
    """
    errors = []
    if re.search(r"(?:/Users/|/home/|[A-Za-z]:\\)", body):
        errors.append("正文包含本机绝对路径。")
    if any(name not in EXPECTED_SKILLS for name in re.findall(r"\bshiao-[a-z0-9-]+\b", body)):
        errors.append("正文依赖未纳入本包的项目 Skill。")
    for target in re.findall(r"\]\(([^\n)]+)\)", body):
        target = target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        try:
            parsed = urlsplit(target)
        except ValueError:
            errors.append("链接格式不受支持。")
            continue
        if parsed.scheme in {"https", "http"}:
            if not parsed.netloc:
                errors.append("外部链接缺少主机名。")
            continue
        if parsed.scheme or parsed.netloc or target.startswith(("/", "~", "\\")):
            errors.append("仅支持仓库内相对路径或 HTTP(S) 链接。")
            continue
        if not parsed.path:
            continue
        destination = path.parent / unquote(parsed.path)
        if not destination.resolve().is_relative_to(root.resolve()):
            errors.append("本地链接越出仓库。")
        elif not destination.exists() or destination.is_symlink():
            errors.append("本地链接不存在或是符号链接。")
    return sorted(set(errors))


def validate_bundle(root):
    """Validate exactly five independent technical Skills. / 验证恰好五个独立技术技能。

    Args / 参数: root is an existing repository directory / 现有仓库目录。
    Returns / 返回: JSON-compatible report with hashes and fixed errors / 含摘要与固定错误的报告。
    Effects / 副作用: reads bundle files only / 仅读取包内文件。不读取私人归档或运行技能。
    """
    errors = []
    skill_root = root / ".agents/skills"
    if not skill_root.is_dir() or skill_root.is_symlink():
        raise ValueError("技能根目录不可用。")
    directories = {path.name for path in skill_root.iterdir() if path.is_dir()}
    if directories != set(EXPECTED_SKILLS):
        errors.append("技能目录必须恰好包含本包声明的五个名称。")
    try:
        agents_path = root / "AGENTS.md"
        if agents_path.is_symlink() or not agents_path.resolve().is_relative_to(root.resolve()):
            raise ValueError("外部入口不可用。")
        agents = agents_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        agents = ""
        errors.append("AGENTS.md 无法读取。")
    results = []
    for name in EXPECTED_SKILLS:
        relative = ".agents/skills/" + name + "/SKILL.md"
        path = root / relative
        findings = []
        digest = None
        try:
            if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("技能文件不得是符号链接或仓库外文件。")
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            metadata, body = parse_frontmatter(raw.decode("utf-8"))
            if metadata["name"] != name:
                findings.append("frontmatter 名称与目录不一致。")
            findings.extend(validate_links(root, path, body))
        except (OSError, UnicodeError):
            findings.append("技能文件不存在或无法按 UTF-8 读取。")
        except ValueError as error:
            findings.append(str(error))
        if "](" + relative + ")" not in agents:
            findings.append("AGENTS.md 缺少指向该技能的相对路径路由。")
        results.append({"name": name, "path": relative, "sha256": digest,
                        "status": "failed" if findings else "passed", "errors": findings})
    return {
        "status": "failed" if errors or any(item["errors"] for item in results) else "passed",
        "skill_count": len(results), "errors": errors, "skills": results,
        "parser": "restricted_frontmatter_v1; not a full YAML parser",
        "runtime_discovery_verified": False,
        "behavior_evaluation_performed": False,
        "limitations": ["仅支持本包两个单行纯文本字段，不支持任意 YAML。", "只验证结构、路由、本地链接及当前文件摘要；未验证应用重新载入、自动选择或技能行为。", "文件摘要记录当前字节，不是带签名的历史来源或篡改防护基线。"],
    }


def main(argv=None):
    """Validate CLI inputs and optionally save the report. / 验证命令输入并按需保存报告。

    Args / 参数: argv optionally supplies argument strings / 可选命令参数。
    Returns / 返回: 0 for valid bundle, 1 for findings, 2 for input errors / 有效为0，发现问题为1，输入错误为2。
    Effects / 副作用: reads files, prints report, optionally writes --json / 读取、输出及按需写报告。
    """
    parser = argparse.ArgumentParser(description="Validate five portable technical Skills / 验证五个可移植技术技能")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", type=Path, dest="report_path")
    args = parser.parse_args(argv)
    try:
        if not args.root.is_dir():
            raise ValueError("仓库根目录不可用。")
        report = validate_bundle(args.root.resolve())
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report_path:
            args.report_path.parent.mkdir(parents=True, exist_ok=True)
            args.report_path.write_text(output, encoding="utf-8")
        print(output, end="")
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError):
        print(json.dumps({"status": "input_error", "message": "输入或报告路径不可用；验证未完成。"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
