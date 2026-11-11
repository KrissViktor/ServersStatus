import unittest
from deploy.translate_release_notes import translation,ENGLISH_NOTES
from agent.publish_release import RELEASE_NOTES,release_title


class ReleaseTranslationTest(unittest.TestCase):
    def test_existing_release_translation_keeps_technical_identifiers(self):
        tag='agent-windows-0123456789ab'
        changes=translation({'tag_name':tag,'name':tag,'body':ENGLISH_NOTES})
        self.assertEqual(changes,{'name':'Агент ServersStatus для Windows · 0123456789ab','body':RELEASE_NOTES})
        self.assertNotIn('tag_name',changes)
        self.assertNotIn('assets',changes)

    def test_repeat_is_idempotent(self):
        tag='agents-stable'
        self.assertEqual(translation({'tag_name':tag,'name':release_title(tag),'body':RELEASE_NOTES}),{})

    def test_custom_description_requires_translation(self):
        with self.assertRaises(ValueError):translation({'tag_name':'custom','body':'Special installation instructions'})
        self.assertEqual(translation({'tag_name':'custom','name':'Особая сборка','body':'Особые инструкции'}),{})

    def test_new_release_titles_are_russian(self):
        self.assertEqual(release_title('agent-linux-abcd'),'Агент ServersStatus для Linux · abcd')
        self.assertEqual(release_title('agents-stable'),'Агенты ServersStatus — стабильный канал')
