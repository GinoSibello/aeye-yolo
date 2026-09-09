"""Comprueba adaptadores y sincronizacion sin tocar datos ni configuracion real."""

from pathlib import Path
import shutil
import tempfile
import unittest

from tools.sync_agent_skills import ROOT, frontmatter, synchronize, validate_sources


class AgentStructureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("skills", ".codex", ".opencode"):
            shutil.copytree(ROOT / name, self.root / name)
        for name in ("AGENTS.md", "AGENT_WORKFLOW.md"):
            shutil.copy2(ROOT / name, self.root / name)
        # Los links locales de la guia apuntan a estos archivos de soporte.
        for name in ("tools", "tests"):
            (self.root / name).mkdir()
        for name in ("tools/sync_agent_skills.py", "tests/test_agent_structure.py",
                     "requirements-agent-tools.txt"):
            shutil.copy2(ROOT / name, self.root / name)

    def test_repository_is_synchronized(self):
        count, created = synchronize(ROOT, check=True)
        self.assertEqual(count, 9)
        self.assertEqual(created, 0)

    def test_missing_check_does_not_write(self):
        with self.assertRaisesRegex(ValueError, "Faltan enlaces"):
            synchronize(self.root, check=True)
        self.assertFalse((self.root / ".agents").exists())

    def test_creates_relative_links_and_is_idempotent(self):
        self.assertEqual(synchronize(self.root), (9, 9))
        self.assertEqual(synchronize(self.root), (9, 0))
        link = self.root / ".agents/skills/aeye-api"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink(), Path("../../skills/aeye-api"))
        self.assertEqual(frontmatter(link / "SKILL.md")[0]["name"], "aeye-api")

    def test_conflicting_directory_is_not_overwritten(self):
        destination = self.root / ".agents/skills/aeye-web"
        destination.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "No se sobrescribe"):
            synchronize(self.root)
        self.assertTrue(destination.is_dir())
        self.assertFalse((destination.parent / "aeye-api").exists())

    def test_broken_link_is_not_replaced(self):
        destination = self.root / ".agents/skills/aeye-api"
        destination.parent.mkdir(parents=True)
        destination.symlink_to("../../missing")
        with self.assertRaisesRegex(ValueError, "Enlace conflictivo"):
            synchronize(self.root)
        self.assertEqual(destination.readlink(), Path("../../missing"))

    def test_symlinked_parent_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / ".agents").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Destino padre"):
            synchronize(self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_unmanaged_destinations_are_not_deleted(self):
        destination = self.root / ".agents/skills/unrelated"
        destination.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "no administrados"):
            synchronize(self.root)
        self.assertTrue(destination.exists())

    def test_name_must_match_directory(self):
        path = self.root / "skills/aeye-api/SKILL.md"
        path.write_text(path.read_text().replace("name: aeye-api", "name: wrong"))
        with self.assertRaisesRegex(ValueError, "nombre invalido"):
            validate_sources(self.root)

    def test_review_permissions_cannot_silently_expand(self):
        path = self.root / ".opencode/agents/aeye-review.md"
        path.write_text(path.read_text().replace('"*": deny', '"*": allow'))
        with self.assertRaisesRegex(ValueError, "restrictivos"):
            validate_sources(self.root)

    def test_adapter_must_point_to_its_skill(self):
        path = self.root / ".codex/agents/aeye-api.toml"
        path.write_text(path.read_text().replace("skills/aeye-api/", "skills/absent/"))
        with self.assertRaisesRegex(ValueError, "inconsistente"):
            validate_sources(self.root)


if __name__ == "__main__":
    unittest.main()
