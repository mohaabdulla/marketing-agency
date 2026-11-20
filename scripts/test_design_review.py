"""Design Lab: measured grading, bounded research moves, guideline-safe improvements and real renders. No network."""
import colorsys
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='design-review-')
os.environ['DESIGN_RESEARCH_CACHE'] = str(Path(TEMP.name) / 'cache')
from PIL import Image, ImageDraw
import image.design_review as lab
from image.visual_engine import resolve_brand_theme

DUNE = dict(brand_name='Dune Realty', brand_colors=dict(primary='#3a4a50', accent='#5f7f7a'))
CARD = dict(card_title='Dune Realty', card_subtitle='Homes by the sea', hero_hook='New waterfront homes now open for viewing',
            subcopy='Two- and three-bedroom homes with private terraces. Viewings run every weekend this month.',
            chips=['Waterfront', 'Private terraces', 'Weekend viewings'], focus_areas=['Two bedrooms', 'Sea views'], cta_text='Book a viewing', cta_url='')


def card_image(path, background, accent, size=(1080, 1350)):
    image = Image.new('RGB', size, background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 300, 1000, 420), fill=accent)
    draw.rectangle((80, 1100, 500, 1180), fill=(240, 240, 240))
    image.save(path)
    return path


class DesignReviewTests(unittest.TestCase):
    def test_grade_measures_real_pixels(self):
        folder = Path(TEMP.name)
        strong = card_image(folder / 'strong.png', (14, 20, 30), (90, 200, 120))
        weak = card_image(folder / 'weak.png', (60, 70, 75), (80, 95, 100))
        brand = lambda accent: dict(primary_hex=accent, secondary_hex='#f0f0f0')
        good, poor = lab.grade(strong, brand('#5ac878')), lab.grade(weak, brand('#505f64'))
        self.assertGreater(good['score'], poor['score'])
        by_id = lambda g: {c['id']: c for c in g['criteria']}
        self.assertEqual(by_id(good)['accent-contrast']['score'], 100)
        self.assertLess(by_id(poor)['accent-contrast']['score'], 50)
        self.assertEqual(by_id(good)['format']['score'], 100)
        self.assertTrue(all(c['source'] is None or c['source']['url'].startswith('https://') for c in good['criteria']))
        square = card_image(folder / 'square.png', (14, 20, 30), (90, 200, 120), (1080, 1080))
        self.assertLess(by_id(lab.grade(square, brand('#5ac878')))['format']['score'], 100)

    def test_contrast_moves_keep_hue_and_never_reduce_readability(self):
        theme = resolve_brand_theme(brand_profile=DUNE, brand_name='Dune Realty', post_type='product_launch')
        moves = lab.bounded(dict(cta_colour='accent', accent_vibrance=.2))      # the move that once darkened the headline line
        better = lab.improved_theme(theme, moves)
        for colour in (better.primary_accent, better.secondary_accent):
            self.assertGreaterEqual(min(lab.contrast(colour, b) for b in (better.bg_dark_start, better.bg_dark_end)), 4.5)
        guideline = min(lab.contrast(theme.secondary_accent, b) for b in (theme.bg_dark_start, theme.bg_dark_end))
        improved = min(lab.contrast(better.secondary_accent, b) for b in (better.bg_dark_start, better.bg_dark_end))
        self.assertGreaterEqual(improved, min(7, guideline) - .01)
        hue = lambda rgb: colorsys.rgb_to_hls(*(c / 255 for c in rgb))[0]
        self.assertAlmostEqual(hue(better.primary_accent), hue(theme.primary_accent), delta=.03)
        changes = lab.guideline_changes(theme, better)
        self.assertTrue(any(not c['within_guideline'] for c in changes))
        self.assertTrue(all(c['guideline'].startswith('#') and c['delta_e'] >= 1 for c in changes))

    def test_plan_targets_only_weak_criteria_and_clamps_model_moves(self):
        def graded(**scores):
            criteria = [dict(id=key, score=scores.get(key.replace('-', '_'), 100)) for key in
                        ('brand-presence', 'colour-balance', 'accent-contrast', 'thumbnail', 'focal-point', 'negative-space', 'colourfulness')]
            return dict(criteria=criteria, measured=dict(colourfulness=60, accent_contrast=6, secondary_contrast=8))
        strong = lab.plan(graded(), dict(background='lighten', accent_vibrance=.3, copy_density='reduce', cta_colour='accent'))
        self.assertEqual((strong['background'], strong['accent_vibrance'], strong['copy_density'], strong['cta_colour']), ('keep', 0., 'keep', 'keep'))
        weak = lab.plan(graded(thumbnail=50, colourfulness=30, negative_space=60), dict(background='lighten'))
        self.assertEqual(weak['background'], 'lighten')
        self.assertEqual(weak['cta_colour'], 'vivid')
        self.assertEqual(weak['copy_density'], 'reduce')
        junk = lab.bounded(dict(accent_vibrance='a lot', spotlight=9, background='neon', cta_colour='rainbow'))
        self.assertEqual((junk['accent_vibrance'], junk['spotlight'], junk['background'], junk['cta_colour']), (0., .2, 'keep', 'keep'))

    def test_lighter_copy_never_blanks_fields_the_renderer_would_fill(self):
        lighter = lab.lighter_copy(CARD)
        self.assertEqual(lighter['subcopy'], 'Two- and three-bedroom homes with private terraces.')
        self.assertEqual(lighter['focus_areas'], [])
        self.assertEqual(lighter['chips'], CARD['chips'])

    def test_research_is_private_sourced_and_falls_back(self):
        with patch.object(lab, '_search', return_value=[]), patch('video.script_writer.chat', side_effect=RuntimeError('offline')):
            result = lab.research(lab.industry_of('Launch of Acme Towers waterfront apartments'), 'instagram', 'product_launch', 'en')
        self.assertEqual(result['industry'], 'real estate')
        self.assertTrue(all('acme' not in q.lower() and 'towers' not in q.lower() for q in result['queries_sent']))
        self.assertEqual(result['engine'], 'built-in rules')
        self.assertTrue(result['note'])
        self.assertTrue(all(f['url'].startswith('https://') for f in result['findings']))
        web = [dict(title='Real estate Instagram design trends 2026', url='https://example.com/trends', description='Bold colour and clean layouts')]
        answer = dict(findings=[dict(claim='Bold accents stand out.', source_id=0), dict(claim='Invented.', source_id=99)],
                      moves=dict(background='deepen', spotlight=5), reasons=dict(background='Darker reads better.'))
        with patch.object(lab, '_search', return_value=web), patch.object(lab, '_page_text', return_value=''), \
                patch('video.script_writer.chat', return_value=(answer, 'test-model')):
            result = lab.research('retail', 'instagram', 'general', 'en')
        self.assertEqual([f['url'] for f in result['findings']], ['https://example.com/trends'])   # uncited claim dropped
        self.assertEqual(result['moves']['spotlight'], .2)
        self.assertEqual(result['engine'], 'test-model')
        self.assertTrue(lab.research('retail', 'instagram', 'general', 'en')['cached'])

    def test_search_drops_navigation_and_unrelated_results(self):
        hits = [dict(title='Instagram', url='https://www.instagram.com/', description='Log in'),
                dict(title='Shipment tracking', url='https://example.com/track', description='Track your container'),
                dict(title='Instagram post design ideas', url='https://example.com/design', description='Colour and layout tips')]
        with patch('video.company_research.searxng_search', return_value=hits):
            self.assertEqual([h['url'] for h in lab._search('q')], ['https://example.com/design'])

    def test_design_lab_renders_and_grades_both_versions(self):
        folder = Path(TEMP.name) / 'lab'; folder.mkdir()
        theme = resolve_brand_theme(brand_profile=DUNE, brand_name='Dune Realty', post_type='product_launch')
        from image.visual_engine import render_agency_card
        delivered = folder / 'delivered.jpg'
        render_agency_card(dict(CARD), theme, post_type='product_launch', language='en').convert('RGB').save(delivered)
        gif = folder / 'loop.gif'
        frames = [Image.new('RGB', (216, 270), (10 * i, 40, 60)) for i in range(8)]
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
        research = dict(industry='real estate', findings=[], moves={}, reasons={})
        report = lab.design_lab(theme=theme, request=dict(prompt='Waterfront homes', post_type='product_launch'), copies={},
                                base=dict(card_copy=dict(en=CARD)), language='en', folder=folder, delivered_image=delivered,
                                delivered_gif=gif, research_result=research, make_gif=False)
        for key in ('guideline', 'improved'):
            self.assertTrue(Path(report[key]['image']).is_file())
            with Image.open(report[key]['image']) as rendered:
                self.assertEqual(rendered.size, (1080, 1350))
        self.assertGreater(report['improved']['grade']['score'], report['guideline']['grade']['score'])
        motion = report['motion']['delivered']
        self.assertTrue(motion['loops_forever'])
        self.assertAlmostEqual(motion['seconds'], .8, delta=.05)
        from agency.enterprise_pipeline import design_presentation
        published = design_presentation(report, lambda path: 'https://host/renders/x/' + Path(path).name)
        self.assertEqual(published['guideline']['image_url'], 'https://host/renders/x/design-guideline-en.jpg')
        self.assertNotIn(str(folder), str(published))


class PublishedKitTests(unittest.TestCase):
    def test_background_lab_report_joins_the_published_kit(self):
        import json
        from concurrent.futures import Future
        from types import SimpleNamespace
        from agency import enterprise_pipeline as pipeline
        from image.visual_engine import render_agency_card
        root = Path(TEMP.name) / 'published'; folder = root / ('a' * 32); folder.mkdir(parents=True)
        (folder / '_complete.json').write_text('{}'); (folder / '_presentation.json').write_text(json.dumps(dict(design_review=dict(status='running'))))
        self.assertEqual(pipeline.presentation_for(root, 'a' * 32)['design_review']['status'], 'running')
        theme = resolve_brand_theme(brand_profile=DUNE, brand_name='Dune Realty', post_type='product_launch')
        render_agency_card(dict(CARD), theme, post_type='product_launch').convert('RGB').save(folder / 'primary-en.jpg')
        frames = [Image.new('RGB', (108, 135), (20 * i, 40, 60)) for i in range(6)]
        frames[0].save(folder / 'motion-en.gif', save_all=True, append_images=frames[1:], duration=100, loop=0)
        done = Future(); done.set_result(dict(industry='real estate', findings=[], moves={}, reasons={}))
        frozen = SimpleNamespace(prompt='Waterfront homes', post_type='product_launch',
                                 model_dump=lambda: dict(prompt='Waterfront homes', post_type='product_launch'))
        with patch('image.design_review.design_lab', wraps=lab.design_lab) as run:
            pipeline.finish_design_lab(done, frozen, theme, {}, dict(card_copy=dict(en=CARD)),
                                       dict(image_url='/stage/primary-en.jpg', animation_url='/stage/motion-en.gif'), 'en', folder, None,
                                       lambda path: 'https://host/renders/' + 'a' * 32 + '/' + Path(path).name)
        self.assertEqual(run.call_args.kwargs['delivered_image'], folder / 'primary-en.jpg')
        review = pipeline.presentation_for(root, 'a' * 32)['design_review']
        self.assertEqual(review['status'], 'ready')
        self.assertTrue(review['improved']['image_url'].endswith('/design-improved-en.jpg'))
        self.assertTrue((folder / 'design-improved-en.jpg').is_file())
        self.assertNotIn(str(folder), json.dumps(review))
        failed = Future(); failed.set_exception(RuntimeError('offline'))
        (folder / 'primary-en.jpg').unlink()
        pipeline.finish_design_lab(failed, frozen, theme, {}, {}, dict(image_url='primary-en.jpg', animation_url='motion-en.gif'),
                                   'en', folder, None, str)
        self.assertEqual(pipeline.presentation_for(root, 'a' * 32)['design_review']['status'], 'unavailable')


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        TEMP.cleanup()
