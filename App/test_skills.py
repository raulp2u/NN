from pathlib import Path
import unittest

try:
    import yaml
except ImportError:
    yaml = None

SKILLS = Path(__file__).parent.parent / "Skills"


@unittest.skipIf(yaml is None, "Validação das skills requer requirements-dev.txt")
class SkillTests(unittest.TestCase):
    def test_frontmatter_name_description_and_body(self):
        paths = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertEqual(len(paths), 6)
        for path in paths:
            with self.subTest(skill=path.parent.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"), "Frontmatter ausente")
                header, body = text[4:].split("\n---\n", 1)
                metadata = yaml.safe_load(header)
                self.assertEqual(set(metadata), {"name", "description"})
                self.assertEqual(metadata["name"], path.parent.name)
                self.assertRegex(metadata["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertTrue(10 <= len(metadata["description"]) <= 1024)
                self.assertTrue(body.strip(), "Corpo da skill vazio")


if __name__ == "__main__":
    unittest.main()
