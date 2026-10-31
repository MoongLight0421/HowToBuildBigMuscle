.PHONY: check test check-engineering check-skills
PYTHON ?= python3

# Run portable local gates. / 运行可移植本地检查。
check: test check-engineering check-skills

# Exercise synthetic temporary projects. / 使用临时合成项目验证检查器。
test:
	$(PYTHON) -m unittest discover -s scripts/tests -p 'test_*.py' -v

# No application source is explicitly reported as skipped. / 无应用源码时明确报告跳过。
check-engineering:
	$(PYTHON) scripts/engineering_harness.py --json .reports/harness-report.json

# Validate only this bundle, without private source baselines. / 仅验证当前技术包，不依赖私人基线。
check-skills:
	$(PYTHON) scripts/validate_technical_skills.py --json .reports/technical-skills.json
