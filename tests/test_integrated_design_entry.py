"""The production shell must load its immutable design entry before native UI execution."""
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://sonchanggi.github.io/quant-dashboard/shared/design/startup/1.2.0/'

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
    from factor_lab.design_contract.verify_design import verify_html
    for path in [ROOT / 'factor_lab/web/integrated.html', ROOT / 'site/index.html']:
        result = verify_html(path.read_text(), 'factor')
        assert result['startup'] == '1.2.0' and result['ui'] == '0.7.0'
        parser = HeadAssets()
        parser.feed(path.read_text())
        native = [a for tag, a in parser.tags if tag == 'script' and a.get('src', '').startswith('assets/')]
        assert native and all('defer' in a for a in native)


def test_published_chart_asset_query_matches_actual_renderer_bytes():
    digest = sha256((ROOT / 'site/assets/integrated_charts.js').read_bytes()).hexdigest()[:12]
    assert f'assets/integrated_charts.js?v={digest}"' in (ROOT / 'site/index.html').read_text()


import json
import re
import shutil
import pytest
from factor_lab.design_contract.verify_design import verify_html


def mutated_design(html, mutation):
    startup = re.search(r'<script[^>]*data-quant-design-project="factor"[^>]*></script>', html).group()
    nav = re.search(r'<script[^>]*data-quant-project="factor"[^>]*></script>', html).group()
    if mutation == 'old-pin':
        return html.replace('/startup/1.2.0/', '/startup/1.1.0/')
    if mutation == 'missing-start':
        return html.replace(startup, '')
    if mutation == 'duplicate-start':
        return html.replace(startup, startup * 2)
    if mutation == 'async-start':
        return html.replace(startup, startup.replace('<script', '<script async'))
    if mutation == 'duplicate-nav':
        return html.replace(nav, nav * 2)
    if mutation == 'late-style':
        return html.replace('</head>', '<link rel="stylesheet" href="assets/late.css"></head>')
    return html.replace('<head>', '<head><script defer src="assets/integrated.js"></script>')


@pytest.mark.parametrize('mutation', ['old-pin', 'missing-start', 'duplicate-start', 'async-start', 'duplicate-nav', 'late-style', 'early-app'])
def test_generated_design_rejects_regression_even_with_refreshed_manifest(tmp_path, mutation):
    from scripts.validate_integrated_publication import validate
    from scripts.build_integrated_publication import build
    site = tmp_path / 'site'
    site.mkdir()
    html = mutated_design((ROOT / 'site/index.html').read_text(), mutation)
    (site / 'index.html').write_text(html)
    (site / 'publication.json').write_text(json.dumps({'files': {'index.html': sha256(html.encode()).hexdigest()}}))
    with pytest.raises(ValueError, match='Design contract:'):
        validate(site)
    output = tmp_path / 'public'
    with pytest.raises(ValueError, match='Design contract:'):
        build(output, site=site)
    assert not output.exists()


def test_service_rejects_old_template_before_touching_existing_result(tmp_path, monkeypatch):
    import factor_lab.integrated_service as service
    source = tmp_path / 'source'
    (source / 'web').mkdir(parents=True)
    (source / 'web/integrated.html').write_text(mutated_design((ROOT / 'factor_lab/web/integrated.html').read_text(), 'old-pin'))
    monkeypatch.setattr(service, '__file__', str(source / 'integrated_service.py'))
    site = tmp_path / 'site'
    (site / 'data').mkdir(parents=True)
    previous = site / 'data/integrated-result.json'
    previous.write_bytes(b'unchanged last good')
    with pytest.raises(ValueError, match='Design contract:'):
        service.build_site(site, {})
    assert previous.read_bytes() == b'unchanged last good'
    assert not (site / 'assets').exists()


PREFERENCES = '<script src="https://sonchanggi.github.io/quant-dashboard/shared/preferences/1.0.0/preferences.js"></script>'


def test_preferences_restore_precedes_native_theme_and_startup():
    for path in [ROOT / 'factor_lab/web/integrated.html', ROOT / 'site/index.html']:
        html = path.read_text()
        assert html.count(PREFERENCES) == 1
        assert html.index(PREFERENCES) < html.index('quant-research-theme') < html.index(BASE + 'start.js')


@pytest.mark.parametrize('mutation', ['duplicate', 'defer', 'async', 'module', 'late', 'untrusted'])
def test_preferences_cannot_bypass_startup_contract(mutation):
    html = (ROOT / 'site/index.html').read_text()
    if mutation == 'duplicate':
        html = html.replace(PREFERENCES, PREFERENCES * 2)
    elif mutation in {'defer', 'async'}:
        html = html.replace(PREFERENCES, PREFERENCES.replace('<script ', '<script ' + mutation + ' '))
    elif mutation == 'module':
        html = html.replace(PREFERENCES, PREFERENCES.replace('<script ', '<script type="module" '))
    elif mutation == 'late':
        html = html.replace(PREFERENCES, '').replace('</head>', PREFERENCES + '</head>')
    else:
        html = html.replace(PREFERENCES, PREFERENCES.replace('sonchanggi.github.io', 'example.com'))
    with pytest.raises(ValueError, match='Design contract:'):
        verify_html(html, 'factor')
