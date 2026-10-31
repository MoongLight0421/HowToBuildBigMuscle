"""Test portable Skill validation in isolation. / 隔离测试可移植技能验证。"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("validate_technical_skills", PROJECT / "scripts/validate_technical_skills.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class TechnicalSkillTests(unittest.TestCase):
    """Exercise valid and rejected portable inputs. / 验证有效输入与应拒绝输入。"""

    def setUp(self):
        """Create exactly five synthetic Skills. / 创建恰好五个合成技能。

        Args / 参数: self is this test / 当前测试实例。
        Returns / 返回: None. Effects / 副作用: writes temporary fixtures only / 仅写临时样例。
        """
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.paths = {}
        routes = []
        (self.root / "engineering").mkdir()
        (self.root / "engineering/DEVELOPMENT_STANDARDS.md").write_text("# Synthetic standard", encoding="utf-8")
        for name in VALIDATOR.EXPECTED_SKILLS:
            path = self.root / ".agents/skills" / name / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\nname: " + name + "\ndescription: 合成技术技能用于测试\n---\n\n# Purpose\n[Standard](../../../engineering/DEVELOPMENT_STANDARDS.md)\n", encoding="utf-8")
            self.paths[name] = path
            routes.append("[" + name + "](.agents/skills/" + name + "/SKILL.md)")
        (self.root / "AGENTS.md").write_text("\n".join(routes), encoding="utf-8")

    def test_valid_portable_bundle_has_no_private_baseline(self):
        """Accept a complete bundle without Ruby or source archives. / 无需 Ruby 或原始归档即可接受完整包。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Effects / 副作用: reads temporary inputs and asserts / 读取临时输入并断言。
        """
        report = VALIDATOR.validate_bundle(self.root)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["skill_count"], 5)
        self.assertFalse(report["runtime_discovery_verified"])
        self.assertFalse(report["behavior_evaluation_performed"])
        self.assertTrue(all(len(item["sha256"]) == 64 for item in report["skills"]))

    def test_unsupported_yaml_variants_are_rejected(self):
        """Reject unsupported YAML instead of guessing its meaning. / 拒绝不支持的 YAML 而不猜测含义。

        Args / 参数: self supplies a valid baseline / 当前实例提供有效基线。
        Returns / 返回: None. Effects / 副作用: parses synthetic strings only / 仅解析合成字符串。
        """
        values = ['"quoted"', "'quoted'", "|", ">", "&anchor test", "*alias", "!tag test", "[a,b]", "{a: b}", "text # comment", "true", "2026-10-31", "12", "1e3", "0xABC", "? mapping", " value"]
        for value in values:
            with self.subTest(kind=value):
                with self.assertRaises(ValueError):
                    VALIDATOR.parse_frontmatter("---\nname: shiao-product-spec\ndescription: " + value + "\n---\n# Body")
        for header in ["name: shiao-product-spec\nname: duplicate", "name: shiao-product-spec\ndescription: valid\nmetadata: extra", "name: shiao-product-spec", "name: UPPER\ndescription: valid", "name: shiao-product-spec\ndescription: valid\n next line", "name: shiao-product-spec\ndescription: valid\n"]:
            with self.subTest(header=header):
                with self.assertRaises(ValueError):
                    VALIDATOR.parse_frontmatter("---\n" + header + "\n---\n# Body")

    def test_missing_extra_and_mismatched_skills_fail(self):
        """Reject incomplete or renamed bundle members. / 拒绝缺失、多余或名称不符的技能。

        Args / 参数: self supplies fixture paths / 当前实例提供样例路径。
        Returns / 返回: None. Effects / 副作用: mutates temporary files / 修改临时文件。
        """
        path = self.paths["shiao-product-spec"]
        original = path.read_text(encoding="utf-8")
        path.unlink()
        self.assertEqual(VALIDATOR.validate_bundle(self.root)["status"], "failed")
        path.write_text(original.replace("name: shiao-product-spec", "name: other-skill"), encoding="utf-8")
        self.assertEqual(VALIDATOR.validate_bundle(self.root)["status"], "failed")
        path.write_text(original, encoding="utf-8")
        (self.root / ".agents/skills/extra-skill").mkdir()
        self.assertEqual(VALIDATOR.validate_bundle(self.root)["status"], "failed")

    def test_missing_outside_and_absolute_links_fail_without_echo(self):
        """Reject broken or nonportable references without echoing inputs. / 拒绝断链和不可移植引用且不回显输入。

        Args / 参数: self supplies temporary Skill / 当前实例提供临时技能。
        Returns / 返回: None. Effects / 副作用: rewrites one fixture and asserts / 重写一个样例并断言。
        """
        path = self.paths["shiao-product-spec"]
        baseline = path.read_text(encoding="utf-8")
        for target in ["missing.md", "../../../../outside.md", "/Users/synthetic/private.md", "file:///private/secret", "https://", "https://[synthetic-secret"]:
            path.write_text(baseline + "\n[Bad](" + target + ")", encoding="utf-8")
            report = VALIDATOR.validate_bundle(self.root)
            self.assertEqual(report["status"], "failed")
            self.assertNotIn(target, json.dumps(report))

    def test_unavailable_skill_and_missing_route_fail(self):
        """Reject hidden bundle dependencies and absent entry routing. / 拒绝包外技能依赖与缺失入口路由。

        Args / 参数: self supplies fixture Skill / 当前实例提供样例技能。
        Returns / 返回: None. Effects / 副作用: mutates temporary body and entrypoint / 修改临时正文与入口。
        """
        path = self.paths["shiao-product-spec"]
        baseline = path.read_text(encoding="utf-8")
        path.write_text(baseline + "\nUse shiao-unavailable.", encoding="utf-8")
        self.assertEqual(VALIDATOR.validate_bundle(self.root)["status"], "failed")
        path.write_text(baseline, encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# No routes", encoding="utf-8")
        self.assertEqual(VALIDATOR.validate_bundle(self.root)["status"], "failed")

    def test_cli_exit_codes_and_report(self):
        """Verify success, finding and invalid-input CLI results. / 验证成功、问题及输入错误的命令结果。

        Args / 参数: self supplies fixture root / 当前实例提供样例根目录。
        Returns / 返回: None. Effects / 副作用: writes report and captures stdout / 写报告并捕获输出。
        """
        destination = self.root / ".reports/skills.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(VALIDATOR.main(["--root", str(self.root), "--json", str(destination)]), 0)
            self.assertEqual(VALIDATOR.main(["--root", str(self.root / "missing")]), 2)
            self.paths["shiao-product-spec"].write_bytes(b"\xff")
            self.assertEqual(VALIDATOR.main(["--root", str(self.root)]), 1)
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["status"], "passed")

    def test_symlinked_skill_and_entrypoint_are_rejected(self):
        """Reject symlinks before reading bundle members. / 在读取前拒绝技能和入口的符号链接。

        Args / 参数: self supplies temporary fixture / 当前实例提供临时样例。
        Returns / 返回: None. Effects / 副作用: replaces temporary files with symlinks / 将临时文件替换为符号链接。
        """
        path = self.paths["shiao-product-spec"]
        outside = self.root / "outside.md"
        outside.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()
        path.symlink_to(outside)
        self.assertEqual(VALIDATOR.validate_bundle(self.root)["status"], "failed")
        agents = self.root / "AGENTS.md"
        agents.unlink()
        agents.symlink_to(outside)
        self.assertEqual(VALIDATOR.validate_bundle(self.root)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
