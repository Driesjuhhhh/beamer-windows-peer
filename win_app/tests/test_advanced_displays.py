import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from app_config import default_config
from advanced_displays import AdvancedDisplays, ScreenTile
from display_layout import reverse_layout


SCREEN=dict(id='DISPLAY1',x=0,y=0,width=1920,height=1080)


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def setUp(self):
        self.config=default_config()
        self.config.peer_platform='windows'
        self.app=SimpleNamespace(_config=self.config, sender=Mock(), server=Mock(),
                                 _persist=Mock(), advanced_switch=Mock(), basic_ways=Mock())
        self.patch=patch('advanced_displays.desktop_win.displays',return_value=[SCREEN])
        self.patch.start()
        self.editor=AdvancedDisplays(self.app)
        self.app.sender.send_display_control.return_value=True

    def tearDown(self):
        self.editor.timer.stop()
        self.editor.close()
        self.editor.deleteLater()
        self.patch.stop()

    def test_inventory_shows_both_devices_without_resetting_unsaved_drags_on_repeat(self):
        payload={'action':'inventory','screens':[SCREEN]}
        self.editor.receive(payload)
        tiles=[i for i in self.editor.scene.items() if isinstance(i,ScreenTile)]
        self.assertEqual(len(tiles),2)
        peer=next(i for i in tiles if i.screen['owner']=='peer')
        peer.setPos(2200,100)
        self.editor.receive(payload)
        self.assertEqual(peer.x(),2200)

    def test_apply_persists_and_sends_reversed_ownership(self):
        self.editor.receive({'action':'inventory','screens':[SCREEN]})
        self.editor.apply()
        self.app._persist.assert_called_once()
        data=self.app.sender.send_display_control.call_args.args[0]
        self.assertEqual(data['action'],'layout')
        self.assertEqual(data['screens'],reverse_layout(self.config.screen_layout))

    def test_disconnected_apply_does_not_save(self):
        self.editor.receive({'action':'inventory','screens':[SCREEN]})
        self.app.sender.send_display_control.return_value=False
        self.editor.apply()
        self.assertEqual(self.config.screen_layout, [])
        self.assertIn('disconnected',self.editor.status.text())

    def test_save_failure_does_not_publish_the_layout(self):
        self.editor.receive({'action':'inventory','screens':[SCREEN]})
        self.app._persist.return_value=False
        self.app.sender.send_display_control.reset_mock()
        self.editor.apply()
        self.assertEqual(self.config.screen_layout,[])
        self.app.sender.send_display_control.assert_not_called()

    def test_identify_selected_peer_screen_sends_only_its_identity(self):
        self.editor.receive({'action':'inventory','screens':[SCREEN]})
        peer=next(i for i in self.editor.scene.items() if isinstance(i,ScreenTile) and i.screen['owner']=='peer')
        peer.setSelected(True)
        self.editor.identify()
        self.app.sender.send_display_control.assert_called_with({'action':'identify','id':'DISPLAY1'})

    def test_invalid_remote_layout_does_not_change_saved_config(self):
        self.editor.receive({'action':'layout','screens':[dict(SCREEN,owner='local',id='missing')]})
        self.assertEqual(self.config.screen_layout,[])
        self.app._persist.assert_not_called()

    def test_remote_mode_changes_ui_without_echoing(self):
        self.editor.receive({'action':'mode','enabled':True})
        self.assertTrue(self.config.advanced_crossing)
        self.app.advanced_switch.setChecked.assert_called_with(True)
        self.app.basic_ways.setVisible.assert_called_with(False)

    def test_mac_peer_cannot_control_the_windows_display_editor(self):
        self.config.peer_platform='mac'
        self.editor.receive({'action':'mode','enabled':True})
        self.assertFalse(self.config.advanced_crossing)
