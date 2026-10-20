import io
from contextlib import redirect_stderr
import unittest
from apply_best_retirement import retired_source, guide_page


class RetirementPreparation(unittest.TestCase):
    def test_guard_does_not_reinterpret_or_execute_old_input(self):
        source='calls=[]\ndef main(argv=None):\n    calls.append(argv)\n    return 0\ndef run(args):\n    calls.append(args)\ndef build_site(args):\n    calls.append(args)\n'
        state={};exec(retired_source(source,('main','run','build_site')),state)
        with redirect_stderr(io.StringIO()) as output:self.assertEqual(state['main'](['run','--prices-file','old.csv']),2)
        self.assertIn('자동 변환하지 않습니다',output.getvalue())
        with self.assertRaises(RuntimeError):state['run']({})
        with self.assertRaises(RuntimeError):state['build_site']({})
        self.assertEqual(state['calls'],[])

    def test_guide_preserves_exact_current_nav_and_uses_only_explicit_local_target(self):
        nav='<nav><a href="https://example.com/news">News</a><a>연구 관측소</a><button id="theme-toggle">테마</button></nav>'
        page,_=guide_page('<html><script src="app.js"></script>'+nav+'</html>','http://127.0.0.1:50073/')
        self.assertIn(nav,page);self.assertNotIn('src="app.js"',page);self.assertIn('href="http://127.0.0.1:50073/"',page)
        with self.assertRaises(ValueError):guide_page(nav,'https://sonchanggi.github.io/factor/')

if __name__=='__main__':unittest.main()
