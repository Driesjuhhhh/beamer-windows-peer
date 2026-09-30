import unittest
from dataclasses import replace
import display_layout as layout
import return_edge as geo
from app_config import default_config, config_to_dict, config_from_dict, ConfigError, validate_config


def screen(name, owner, x, y, w=1920, h=1080):
    return dict(id=name, owner=owner, x=x, y=y, width=w, height=h)


class RoutesTests(unittest.TestCase):
    def test_every_direction_maps_to_the_selected_peer_monitor(self):
        for edge, position, pointer, delta in (
            ('right', (1920, 0), (1919, 540), (150, 0)),
            ('left', (-1920, 0), (0, 540), (-150, 0)),
            ('top', (0, -1080), (960, 0), (0, -150)),
            ('bottom', (0, 1080), (960, 1079), (0, 150)),
        ):
            with self.subTest(edge=edge):
                a, b = screen('a', 'local', 0, 0), screen('b', 'peer', *position)
                model = layout.ScreenRoutes([a, b], [a], 100)
                outcome = model.feed([geo.Rect(0,0,1920,1080)], pointer, *delta)
                self.assertEqual(outcome.action, geo.CROSS)
                self.assertEqual(outcome.edge, geo.OPPOSITE[edge])
                self.assertAlmostEqual(outcome.offset, .5, places=2)
                self.assertEqual(model.target_display, 'b')
                self.assertEqual(model.feed([geo.Rect(0,0,1920,1080)],pointer,*delta).action, geo.PASS)

    def test_staggered_displays_only_cross_the_overlapping_span(self):
        a, b = screen('a','local',0,0), screen('b','peer',1920,540)
        model = layout.ScreenRoutes([a,b],[a],100)
        self.assertEqual(model.feed([geo.Rect(0,0,1920,1080)],(1919,200),150,0).action, geo.PASS)
        outcome = model.feed([geo.Rect(0,0,1920,1080)],(1919,810),150,0)
        self.assertEqual(outcome.action, geo.CROSS)
        self.assertAlmostEqual(outcome.offset,.25)

    def test_multiple_peer_screens_select_the_screen_at_the_crossing_height(self):
        a=screen('a','local',0,0,w=1920,h=2160)
        b,c=screen('b','peer',1920,0),screen('c','peer',1920,1080)
        model=layout.ScreenRoutes([a,b,c],[a],100)
        self.assertEqual(model.feed([geo.Rect(0,0,1920,2160)],(1919,1620),150,0).action,geo.CROSS)
        self.assertEqual(model.target_display,'c')

    def test_internal_windows_border_does_not_become_a_portal(self):
        a,b=screen('a','local',0,0),screen('b','peer',1920,0)
        model=layout.ScreenRoutes([a,b],[a],100)
        self.assertEqual(model.feed([geo.Rect(0,0,1920,1080),geo.Rect(1920,0,1920,1080)],(1919,540),150,0).action,geo.PASS)

    def test_missing_display_gaps_overlaps_and_same_device_cannot_cross(self):
        a=screen('a','local',0,0)
        for b in (screen('b','peer',2000,0),screen('b','peer',1700,0),screen('b','local',1920,0)):
            self.assertEqual(layout.contacts([a,b]),[])
        model=layout.ScreenRoutes([a,screen('b','peer',1920,0)],[],100)
        self.assertEqual(model.feed([geo.Rect(0,0,1920,1080)],(1919,540),150,0).action,geo.PASS)

    def test_reverse_layout_preserves_geometry_and_is_an_involution(self):
        screens=[screen('a','local',-1920,0),screen('b','peer',0,0)]
        self.assertEqual(layout.reverse_layout(layout.reverse_layout(screens)),screens)

    def test_landing_uses_monitor_identity_not_the_desktop_extreme(self):
        displays=[screen('a','local',0,0),screen('b','local',1920,0)]
        result=layout.arrival(displays,'b','left',.5)
        self.assertGreaterEqual(result[0],1920)
        self.assertLess(result[0],3840)
        self.assertIsNone(layout.arrival(displays,'removed','left',.5))

    def test_invalid_inventory_and_layout_are_rejected(self):
        base=screen('a','local',0,0)
        for value in (None, {}, [base,base], [dict(base,width=-1)], [dict(base,x=float('nan'))], [dict(base,owner='unknown')]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                layout.validate_layout(value)

    def test_config_roundtrip_and_legacy_default(self):
        config=default_config()
        config.auth_token='test-token'
        config.advanced_crossing=True
        config.screen_layout=[screen('a','local',0,0),screen('b','peer',1920,0)]
        raw=config_to_dict(config)
        restored=config_from_dict(raw)
        self.assertTrue(restored.advanced_crossing)
        self.assertEqual(restored.screen_layout,config.screen_layout)
        raw.pop('advanced_crossing');raw.pop('screen_layout')
        old=config_from_dict(raw)
        self.assertFalse(old.advanced_crossing)
        self.assertEqual(old.screen_layout,[])
        with self.assertRaises(ConfigError):
            validate_config(replace(config,screen_layout=[dict(config.screen_layout[0],width=0)]))
