"""The production shell must load its immutable design entry before native UI execution."""
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://sonchanggi.github.io/quant-dashboard/shared/design/startup/1.1.0/'

class HeadAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.head = False
        self.tags = []

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.head = True
        if self.head and tag in {'script', 'link'}:
            self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == 'head':
            self.head = False


def test_template_and_published_entry_keep_blocking_versioned_design_order():
    for path in [ROOT / 'factor_lab/web/integrated.html', ROOT / 'site/index.html']:
        parser = HeadAssets()
        parser.feed(path.read_text())
        style, entry = parser.tags[-2:]
        assert style[0] == 'link'
        assert style[1]['href'] == BASE + 'factor.css'
        assert 'data-quant-first-paint-css' in style[1]
        assert entry[0] == 'script'
        assert entry[1]['src'] == BASE + 'start.js'
        assert entry[1]['data-quant-design-project'] == 'factor'
        assert not {'defer', 'async', 'type'} & entry[1].keys()
        native = [a for tag, a in parser.tags if tag == 'script' and a.get('src', '').startswith('assets/')]
        assert native and all('defer' in a for a in native)
        assert '/startup/1.0.0/' not in path.read_text()


def test_published_chart_asset_query_matches_actual_renderer_bytes():
    digest = sha256((ROOT / 'site/assets/integrated_charts.js').read_bytes()).hexdigest()[:12]
    assert f'assets/integrated_charts.js?v={digest}"' in (ROOT / 'site/index.html').read_text()
