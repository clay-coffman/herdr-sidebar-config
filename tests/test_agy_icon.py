import unittest
from runtime import logo_for
from configuration import ghostty_mapping


class AgyIconTests(unittest.TestCase):
    def test_agy_font_and_text(self):
        self.assertEqual(logo_for('agy', 'font'), '\ue1a9')
        self.assertEqual(logo_for('agy', 'text'), 'AGY')

    def test_upgrade_mapping_without_duplicates(self):
        old = 'font-codepoint-map = U+E1A0-U+E1A8=Herdr Sidebar Logos\n'
        updated = ghostty_mapping(old)
        self.assertEqual(updated.count('font-codepoint-map'), 1)
        self.assertIn('E1A9', updated)
        self.assertEqual(ghostty_mapping(updated), updated)
