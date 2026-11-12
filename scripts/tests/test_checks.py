import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import checks  # noqa: E402

AUTHORS = {"Ivan", "Arthur", "Andrew"}
WORKSPACES = {
    "ivan": {"name": "Ivan", "github": ["Ivan-GH"], "paths": ["core/", "solution.py"]},
    "arthur": {"name": "Arthur", "github": [], "paths": ["server/", "Dockerfile"]},
    "andrew": {"name": "Andrew", "github": [], "paths": ["web/"]},
}
LOG = """# Decision log

D-1 | 2026-11-12 | Ivan | team | Первое решение.
D-2 | 2026-11-13 | Arthur | server | Второе решение | с чертой внутри текста.
"""


class DecisionLogTest(unittest.TestCase):
    def errors(self, text, base=None):
        return checks.check_decision_log(text, AUTHORS, base)

    def test_valid_log(self):
        self.assertEqual(self.errors(LOG), [])

    def test_gap_in_numbering(self):
        self.assertTrue(self.errors(LOG.replace("D-2 |", "D-3 |")))

    def test_duplicate_number(self):
        self.assertTrue(self.errors(LOG.replace("D-2 |", "D-1 |")))

    def test_bad_format_and_lowercase(self):
        self.assertTrue(self.errors(LOG + "D-3: решение без полей\n"))
        self.assertTrue(self.errors(LOG + "d-3 | 2026-11-13 | Ivan | team | строчная буква\n"))

    def test_unknown_author_scope_and_date(self):
        self.assertTrue(self.errors(LOG + "D-3 | 2026-11-13 | Bob | team | текст\n"))
        self.assertTrue(self.errors(LOG + "D-3 | 2026-11-13 | Ivan | misc | текст\n"))
        self.assertTrue(self.errors(LOG + "D-3 | 2026-02-30 | Ivan | team | текст\n"))

    def test_append_only(self):
        appended = LOG + "D-3 | 2026-11-14 | Andrew | web | Третье.\n"
        self.assertEqual(self.errors(appended, base=LOG), [])
        self.assertTrue(self.errors(LOG.replace("Первое", "Другое"), base=LOG))
        self.assertTrue(self.errors(LOG.split("D-2")[0], base=LOG))


class WorkspacesTest(unittest.TestCase):
    def test_path_owner(self):
        self.assertEqual(checks.path_owner("core/rag/search.py", WORKSPACES), "ivan")
        self.assertEqual(checks.path_owner("solution.py", WORKSPACES), "ivan")
        self.assertEqual(checks.path_owner("Dockerfile", WORKSPACES), "arthur")
        self.assertIsNone(checks.path_owner("docs/decision-log.md", WORKSPACES))
        self.assertIsNone(checks.path_owner("core.py", WORKSPACES))
        self.assertIsNone(checks.path_owner("solution.py.bak", WORKSPACES))

    def test_resolve_owner(self):
        self.assertEqual(checks.resolve_owner(WORKSPACES, explicit=" Ivan\n"), "ivan")
        self.assertIsNone(checks.resolve_owner(WORKSPACES, explicit="bob", branch="ivan/x"))
        self.assertEqual(checks.resolve_owner(WORKSPACES, github_login="ivan-gh"), "ivan")
        self.assertEqual(checks.resolve_owner(WORKSPACES, github_login="stranger", branch="andrew/chat"), "andrew")
        self.assertIsNone(checks.resolve_owner(WORKSPACES, branch="claude/some-task"))
        self.assertIsNone(checks.resolve_owner(WORKSPACES, branch="main"))

    def test_foreign_changes(self):
        paths = ["core/a.py", "web/src/App.tsx", "docs/decision-log.md", "server/main.py"]
        self.assertEqual(
            checks.foreign_changes(paths, "ivan", WORKSPACES),
            {"andrew": ["web/src/App.tsx"], "arthur": ["server/main.py"]},
        )
        self.assertEqual(checks.foreign_changes(["docs/x.md", "README.md"], None, WORKSPACES), {})
        self.assertEqual(set(checks.foreign_changes(paths, None, WORKSPACES)), {"ivan", "andrew", "arthur"})

    def test_real_workspaces_file(self):
        workspaces = checks.load_workspaces()
        self.assertEqual(set(workspaces), {"ivan", "arthur", "andrew"})
        for spec in workspaces.values():
            self.assertTrue(spec["name"] and spec["paths"])
        all_paths = [p for spec in workspaces.values() for p in spec["paths"]]
        self.assertEqual(len(all_paths), len(set(all_paths)), "путь принадлежит двум участникам")


class ForbiddenTest(unittest.TestCase):
    def test_forbidden_names(self):
        for path in ("data/kb/a.md", "knowledge-base.zip", "core/knowledge_base.zip", "server/.env",
                     ".env.local", "server/app.sqlite", "demo_questions.csv", "submission.csv"):
            self.assertIsNotNone(checks.forbidden_reason(path), path)

    def test_allowed_names(self):
        for path in ("data/README.md", ".env.example", "core/retrieval.py", "docs/decision-log.md"):
            self.assertIsNone(checks.forbidden_reason(path), path)

    def test_find_secrets(self):
        key = "sk-" + "a1B2" * 8
        self.assertEqual(checks.find_secrets(f"x = 1\nKEY = '{key}'\n"), [2])
        self.assertEqual(checks.find_secrets("LLM_API_KEY=" + "Zx9" * 10), [1])
        self.assertEqual(checks.find_secrets("LLM_API_KEY=\nLLM_API_KEY=${LLM_API_KEY}\napi_key = os.environ['K']"), [])
        self.assertEqual(checks.find_secrets(f"TOKEN={'q' * 30}  # checks:allow"), [])


if __name__ == "__main__":
    unittest.main()
