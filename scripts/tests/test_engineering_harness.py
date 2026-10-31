"""Exercise policy findings with synthetic files. / 用合成文件验证工程约束检查。"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("engineering_harness", PROJECT / "scripts/engineering_harness.py")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)
POLICY = json.loads((PROJECT / "engineering/harness/policy.json").read_text(encoding="utf-8"))
VALID_TABLE = """CREATE TABLE sample (
 id BIGINT PRIMARY KEY,
 created_by BIGINT NOT NULL,
 created_at DATETIME NOT NULL,
 updated_by BIGINT NOT NULL,
 updated_at DATETIME NOT NULL,
 is_deleted TINYINT NOT NULL DEFAULT 0,
 business_key VARCHAR(64),
 KEY idx_query (is_deleted, business_key)
);"""


class HarnessTests(unittest.TestCase):
    """Verify redaction, layer rules and honest result states. / 验证脱敏、分层规则和结果边界。"""

    def setUp(self):
        """Create an isolated synthetic project. / 创建隔离的合成项目。

        Args / 参数: self is this test case / 当前用例。
        Returns / 返回: None. Side effects / 副作用: creates temporary directory / 创建临时目录。
        """
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write_source(self, path, text):
        """Write one synthetic source file. / 写入一个合成源码文件。

        Args / 参数: path is relative; text is synthetic content / 相对路径与合成内容。
        Returns / 返回: written Path / 写入后的路径。
        Side effects / 副作用: writes under the temporary project / 写入临时项目。
        """
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        return destination

    def report(self):
        """Run the scanner on temporary inputs. / 扫描临时输入。

        Args / 参数: self supplies root / 当前实例提供根目录。
        Returns / 返回: result dictionary / 结果字典。Side effects / 副作用: reads fixtures / 读取样例。
        """
        return HARNESS.run_checks(self.root, POLICY)

    def rules(self):
        """Collect rule IDs from a scan. / 收集检查触发的规则编号。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: set of rule IDs / 规则编号集合。Side effects / 副作用: reads fixtures / 读取样例。
        """
        return {finding["rule"] for finding in self.report()["findings"]}

    def test_empty_project_is_skipped_not_ready(self):
        """Keep no-source results distinct from compliance. / 区分无源码与合规通过。

        Args / 参数: self supplies empty project / 当前实例提供空项目。
        Returns / 返回: None. Side effects / 副作用: assertion failures on regression / 回归时断言失败。
        """
        report = self.report()
        self.assertEqual(report["status"], "skipped_no_application_source")
        self.assertFalse(report["release_ready"])
        self.assertTrue(all(item["status"] == "skipped" for item in report["checks"]))

    def test_vue_boundary_rejects_network_and_sdk(self):
        """Reject direct requests and SDKs in View. / 拒绝视图直连请求与 SDK。

        Args / 参数: self supplies temporary fixtures / 当前实例提供临时样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("frontend/admin/pages/sample.vue", "<script>\nimport request from 'axios';\nuni.request({url: '/api'});\n</script>")
        report = self.report()
        self.assertIn("VIEW001", self.rules())
        self.assertEqual(report["findings"][0]["line"], 3)

    def test_vue_reactive_data_and_separate_request_are_allowed(self):
        """Allow a view consuming separate data and comments. / 允许视图使用独立数据层并忽略注释。

        Args / 参数: self supplies temporary fixtures / 当前实例提供临时样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("frontend/admin/pages/sample.vue", "<template><input v-model=\"state.name\" /></template>\n<script>\n// uni.request({})\nimport { state } from '../data/sample';\n</script>")
        self.write_source("frontend/admin/data/request.ts", "export const request = uni.request; // transport belongs here\n")
        self.assertEqual(self.report()["findings"], [])
        self.assertEqual(self.report()["status"], "passed_limited_static_checks")

    def test_go_layer_directions_and_sdk(self):
        """Reject layer inversion and controller persistence access. / 拒绝逆向层依赖和控制器持久化直连。

        Args / 参数: self supplies temporary fixtures / 当前实例提供临时样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/internal/order/controller/order.go", 'package controller\nimport (\n "example/internal/order/dao"\n "database/sql"\n)\n')
        self.write_source("backend/internal/order/dao/order.go", 'package dao\nimport svc "example/internal/order/service"\n')
        self.assertTrue({"LAYER001", "LAYER002"} <= self.rules())

    def test_valid_go_direction_and_missing_toolchain_boundary(self):
        """Allow controller-service-dao while reporting unavailable execution. / 允许正向依赖且报告执行条件缺失。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and mocks availability / 写样例并模拟工具缺席。
        """
        self.write_source("backend/internal/order/controller/order.go", 'package controller\nimport "example/internal/order/service"\n')
        self.write_source("backend/internal/order/service/order.go", 'package service\nimport "example/internal/order/dao"\n')
        with mock.patch.object(HARNESS.shutil, "which", return_value=None):
            report = self.report()
        self.assertEqual(report["findings"], [])
        tools = {check["check"]: check["status"] for check in report["checks"]}
        self.assertEqual(tools["go_compile_vet_test_race"], "blocked_missing_toolchain")
        self.assertFalse(report["release_ready"])

    def test_sql_locks_and_deletes_are_blocked_in_source_strings(self):
        """Recognize explicit locks/deletes inside source SQL strings. / 识别源码 SQL 字符串中的显式锁与删除。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/dao/query.go", 'package dao\nconst query = "SELECT id FROM sample FOR UPDATE"\nconst removal = `DELETE FROM sample`\n')
        self.assertTrue({"SQL001", "SQL002"} <= self.rules())

    def test_sql_lock_variants_and_executable_comments(self):
        """Reject locking variants and MySQL executable comments. / 拒绝不同显式锁语法与可执行注释。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        statements = ["SELECT * FROM t FOR SHARE", "SELECT * FROM t LOCK IN SHARE MODE", "SELECT GET_LOCK('sample', 1)", "LOCK TABLES sample WRITE", "/*! DELETE FROM sample */"]
        for number, statement in enumerate(statements):
            self.write_source("backend/sql/bad%d.sql" % number, statement)
        self.assertTrue({"SQL001", "SQL002"} <= self.rules())
        self.assertEqual(len(self.report()["findings"]), 5)

    def test_ordinary_transaction_and_optimistic_update_are_allowed(self):
        """Keep ordinary transactions and version predicates valid. / 允许普通事务及版本条件更新。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/sql/optimistic.sql", "-- FOR UPDATE and DELETE FROM are comments\nBEGIN;\nUPDATE sample SET version=version+1 WHERE id=? AND version=? AND is_deleted=0;\nCOMMIT;")
        self.assertEqual(self.report()["findings"], [])

    def test_required_fields_primary_and_delete_default(self):
        """Reject missing audit data and invalid logical deletion defaults. / 拒绝缺失审计字段及错误软删默认值。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/sql/bad.sql", "CREATE TABLE bad(id BIGINT, is_deleted TINYINT DEFAULT 1);")
        self.assertTrue({"DDL001", "DDL002"} <= self.rules())

    def test_valid_table_and_composite_primary_are_distinct(self):
        """Accept a valid independent id and reject a composite key. / 接受独立 id 并拒绝组合主键。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/sql/good.sql", VALID_TABLE)
        self.assertEqual(self.report()["findings"], [])
        self.write_source("backend/sql/good.sql", VALID_TABLE.replace("id BIGINT PRIMARY KEY", "id BIGINT").replace("KEY idx_query", "PRIMARY KEY (id, business_key), KEY idx_query"))
        self.assertIn("DDL002", self.rules())

    def test_query_index_order_in_create_table_and_create_index(self):
        """Enforce the project index prefix for supported syntax. / 对支持的语法执行项目索引首列要求。

        Args / 参数: self supplies fixtures / 当前实例提供样例。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/sql/bad.sql", VALID_TABLE.replace("(is_deleted, business_key)", "(business_key, is_deleted)") + "\nCREATE INDEX idx_second ON sample (business_key, is_deleted);")
        self.assertEqual(sum(item["rule"] == "DDL003" for item in self.report()["findings"]), 2)

    def test_secret_values_are_never_in_report_or_cli(self):
        """Verify recognized secrets never appear in output or JSON. / 确认识别出的秘密不出现在输出或 JSON。

        Args / 参数: self supplies synthetic values / 当前实例提供合成值。
        Returns / 返回: None. Side effects / 副作用: writes fixtures/report and captures stdout / 写样例报告并捕获输出。
        """
        access_key = "AKIA" + "Z" * 16
        secret = "synthetic-sensitive-value-5826"
        self.write_source("backend/config.json", json.dumps({"aws_access_key_id": access_key, "password": secret}))
        destination = self.root / "report.json"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = HARNESS.main(["--root", str(self.root), "--json", str(destination)])
        self.assertEqual(code, 1)
        combined = output.getvalue() + destination.read_text(encoding="utf-8")
        self.assertNotIn(access_key, combined)
        self.assertNotIn(secret, combined)
        self.assertIn("SEC001", combined)

    def test_placeholders_and_environment_expressions_are_not_secrets(self):
        """Allow intentionally empty and explicit environment placeholders. / 允许空值及明确环境变量占位符。

        Args / 参数: self supplies synthetic config / 当前实例提供合成配置。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/.env.example", 'password = ""\napi_key = "${SERVICE_API_KEY}"\nclient_secret = "<FROM_SECRET_STORE>"\n')
        self.assertEqual(self.report()["findings"], [])

    def test_credential_csv_and_private_key_detection(self):
        """Block credential files and recognizable private keys. / 拒绝凭据文件与可识别私钥。

        Args / 参数: self supplies synthetic inputs / 当前实例提供合成输入。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and asserts / 写样例并断言。
        """
        self.write_source("backend/synthetic_credentials.csv", "User name,Password,Console sign-in URL\nsynthetic,synthetic,https://invalid.example")
        self.write_source("backend/key.pem", "-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----")
        self.assertTrue({"SEC001", "SEC002"} <= self.rules())

    def test_excluded_and_symlinked_files_are_not_read(self):
        """Respect the configured boundary and avoid symlink targets. / 遵守扫描边界且不读取符号链接目标。

        Args / 参数: self supplies synthetic files / 当前实例提供合成文件。
        Returns / 返回: None. Side effects / 副作用: writes fixtures and symlink / 写样例与符号链接。
        """
        self.write_source("backend/vendor/bad.go", "DELETE FROM sample")
        self.write_source("backend/harness/bad.sql", "DELETE FROM sample")
        target = self.write_source("data/source/credentials.csv", "Password\nsynthetic")
        link = self.root / "engineering" / "credentials.csv"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        self.assertEqual(self.report()["findings"], [])
        self.assertEqual(self.report()["counts"]["source"], 0)

    def test_oversized_files_fail_instead_of_silent_skip(self):
        """Treat unscanned oversized inputs as gate findings. / 将超限未扫描输入作为检查问题。

        Args / 参数: self supplies synthetic file / 当前实例提供合成文件。
        Returns / 返回: None. Side effects / 副作用: writes fixture and asserts / 写样例并断言。
        """
        self.write_source("backend/query.sql", "SELECT 1;")
        policy = dict(POLICY, maximum_file_bytes=1)
        report = HARNESS.run_checks(self.root, policy)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["findings"][0]["rule"], "INPUT001")

    def test_cli_empty_and_invalid_inputs(self):
        """Verify skipped success and invalid-input exit codes. / 验证无源码与输入错误的退出码。

        Args / 参数: self supplies root / 当前实例提供根目录。
        Returns / 返回: None. Side effects / 副作用: captures printed reports / 捕获输出报告。
        """
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(HARNESS.main(["--root", str(self.root)]), 0)
            self.assertEqual(HARNESS.main(["--root", str(self.root / "missing")]), 2)

    def test_cli_rejects_malformed_policy(self):
        """Reject damaged JSON, wrong types and inaccurate rule lists. / 拒绝损坏 JSON、错误类型及失真的规则清单。

        Args / 参数: self supplies temporary directory / 当前实例提供临时目录。
        Returns / 返回: None. Side effects / 副作用: writes bad policies and captures output / 写入错误策略并捕获输出。
        """
        policies = ["{", "null", "{}", json.dumps(dict(POLICY, source_roots="engineering")), json.dumps(dict(POLICY, rules={"UNIMPLEMENTED": "bad"})), json.dumps(dict(POLICY, maximum_file_bytes=-1)), json.dumps(dict(POLICY, source_roots=["../outside"]))]
        for number, content in enumerate(policies):
            policy_path = self.write_source("bad-policy-%d.json" % number, content)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = HARNESS.main(["--root", str(self.root), "--policy", str(policy_path)])
            self.assertEqual(result, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "input_error")

    def test_unreadable_utf8_is_a_finding(self):
        """Treat unreadable text as an explicit failure. / 将无法读取的文本作为明确失败。

        Args / 参数: self supplies synthetic path / 当前实例提供合成路径。
        Returns / 返回: None. Side effects / 副作用: writes invalid UTF-8 then reads it / 写入并读取非法 UTF-8。
        """
        source = self.write_source("backend/broken.go", "")
        source.write_bytes(b"\xff\xfe\x00")
        report = self.report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["findings"][0]["rule"], "INPUT001")

    def test_vue_html_comment_does_not_trigger_network_rule(self):
        """Ignore request examples inside Vue template comments. / 忽略 Vue 模板注释中的请求示例。

        Args / 参数: self supplies synthetic View / 当前实例提供合成视图。
        Returns / 返回: None. Side effects / 副作用: writes fixture and asserts / 写入样例并断言。
        """
        self.write_source("frontend/admin/sample.vue", '<!--\nuni.request({url: "/api"})\n-->\n<template><input v-model="state.name" /></template>')
        self.assertEqual(self.report()["findings"], [])

    def test_static_source_sql_whitespace_and_block_comments(self):
        """Recognize common escaped SQL whitespace and inner comments. / 识别静态 SQL 转义空白和内部注释。

        Args / 参数: self supplies synthetic Go source / 当前实例提供合成 Go 源码。
        Returns / 返回: None. Side effects / 副作用: writes fixture and asserts / 写入样例并断言。
        """
        self.write_source("backend/dao/query.go", 'package dao\nconst first = "SELECT id FROM sample FOR\\nUPDATE"\nconst second = "SELECT id FROM sample FOR/* c */UPDATE"\nconst url = "https://invalid.example/endpoint"\n')
        findings = self.report()["findings"]
        self.assertEqual([item["rule"] for item in findings], ["SQL001", "SQL001"])
        self.assertEqual([item["line"] for item in findings], [2, 3])

    def test_unsupported_sql_escape_is_an_explicit_limitation(self):
        """Keep unimplemented language evaluation outside claimed coverage. / 将未实现的语言求值保留为明确边界。

        Args / 参数: self supplies a synthetic encoded SQL string / 当前实例提供合成转义 SQL 字符串。
        Returns / 返回: None. Side effects / 副作用: writes fixture and asserts limitation / 写入样例并断言边界。
        """
        self.write_source("backend/dao/query.go", 'package dao\nconst query = "SELECT id FROM sample FOR\\x20UPDATE"\n')
        self.assertEqual(self.report()["findings"], [])
        self.assertFalse(self.report()["release_ready"])

    def test_all_portable_application_roots_are_scanned(self):
        """Cover backend, admin and mobile roots after migration. / 覆盖迁移后的后端、管理端和移动端根目录。

        Args / 参数: self supplies synthetic project / 当前实例提供合成项目。
        Returns / 返回: None. Effects / 副作用: writes three fixtures then scans them / 写入并扫描三个样例。
        """
        self.write_source("backend/dao/query.go", 'package dao\nconst query = "SELECT id FROM sample FOR UPDATE"\n')
        self.write_source("frontend/admin/pages/sample.vue", '<script>fetch("/api");</script>')
        self.write_source("frontend/mobile/pages/sample.vue", '<script>uni.request({url: "/api"});</script>')
        report = self.report()
        self.assertEqual(report["counts"]["source"], 3)
        self.assertEqual({item["path"] for item in report["findings"]}, {"backend/dao/query.go", "frontend/admin/pages/sample.vue", "frontend/mobile/pages/sample.vue"})


if __name__ == "__main__":
    unittest.main()
