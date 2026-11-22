import io
import unittest
from unittest.mock import patch

from src.gitty.client.animation import print_banner


class AnimationTests(unittest.TestCase):
    def test_redirected_output_is_not_delayed(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch('src.gitty.client.animation.time.sleep') as sleep:
            print_banner('Gitty\nChat')
            self.assertEqual(out.getvalue(), 'Gitty\nChat\n')
            sleep.assert_not_called()

    def test_animation_can_be_disabled(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch.object(out, 'isatty', return_value=True), \
                patch.dict('os.environ', {'GITTY_NO_ANIMATION': '1'}), \
                patch('src.gitty.client.animation.time.sleep') as sleep:
            print_banner('Gitty')
            sleep.assert_not_called()
            self.assertEqual(out.getvalue(), 'Gitty\n')

    def test_interrupt_finishes_banner(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch.object(out, 'isatty', return_value=True), \
                patch.dict('os.environ', {}, clear=True), \
                patch('src.gitty.client.animation.time.sleep', side_effect=KeyboardInterrupt):
            print_banner('Gitty\nChat')
            self.assertIn('Gitty\nChat\n', out.getvalue())
            self.assertTrue(out.getvalue().endswith('\033[0m'))

    def test_matrix_wave_animation_completes(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch.object(out, 'isatty', return_value=True), \
                patch.dict('os.environ', {}, clear=True), \
                patch('src.gitty.client.animation.time.sleep') as sleep:
            print_banner('\033[92mGitty\033[0m')
            self.assertEqual(sleep.call_count, 14)
            self.assertIn('\033[92mGitty\033[0m', out.getvalue())
            self.assertTrue(out.getvalue().endswith('\033[0m'))


if __name__ == '__main__':
    unittest.main()
