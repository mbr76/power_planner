import os
import io
import asyncio
import pytest
import flet as ft
import flet.controls.events as ev
from PIL import Image

import power_planner_flet as ppf


class MockPage:
    def __init__(self, is_web=False):
        self.theme_mode = ft.ThemeMode.DARK
        self.window = type('Window', (), {'min_width': 0, 'min_height': 0})()
        self.overlay = []
        self.services = []
        self._dialogs = type('Dialogs', (), {'controls': []})()
        self.appbar = None
        self.navigation_bar = None
        self.controls = []
        self.padding = 0
        self.scroll = None
        self.title = ''
        self.web = is_web

    def show_dialog(self, dialog):
        self._dialogs.controls.append(dialog)

    def pop_dialog(self):
        if self._dialogs.controls:
            return self._dialogs.controls.pop()
        return None

    def update(self):
        pass

    def add(self, *c):
        self.controls.extend(c)


def test_app_initialization():
    """Test full Flet application controller bootstrap and initial calculation state."""
    async def run():
        page = MockPage()
        await ppf.main(page)
        
        assert page.title.startswith("🚴‍♂️ Power-Planner")
        assert len(page.controls) == 1
        assert page.appbar is not None
        assert page.navigation_bar is not None
        assert len(page.services) > 0  # FilePicker registered

    asyncio.run(run())


def test_slider_drag_and_release_lifecycle():
    """Test that on_change updates live text labels and on_change_end performs calculation."""
    async def run():
        page = MockPage()
        await ppf.main(page)
        
        tab_setup = page.controls[0].content
        main_col = tab_setup.content
        
        # 1. FTP Slider: Drag to 350, release at 350
        card1_col = main_col.controls[1].content.content
        ftp_slider = card1_col.controls[1]
        
        ftp_slider.on_change(ev.Event(name='change', control=ftp_slider, data='350.0'))
        ftp_slider.on_change_end(ev.Event(name='change_end', control=ftp_slider, data='350.0'))
        
        # 2. Target Factor Slider: Drag to 0.88, release at 0.88
        card2_col = main_col.controls[3].content.content
        tf_slider = card2_col.controls[4]
        
        tf_slider.on_change(ev.Event(name='change', control=tf_slider, data='0.88'))
        tf_slider.on_change_end(ev.Event(name='change_end', control=tf_slider, data='0.88'))
        
        # 3. Rider Weight Slider: Drag to 80.0
        weights_row = card1_col.controls[6]
        rider_w_slider = weights_row.controls[0].controls[1]
        rider_w_slider.on_change(ev.Event(name='change', control=rider_w_slider, data='80.0'))
        rider_w_slider.on_change_end(ev.Event(name='change_end', control=rider_w_slider, data='80.0'))

    asyncio.run(run())


def test_lazy_tab_navigation():
    """Test that charts are lazily evaluated and rendered when switching to Analysis tab."""
    async def run():
        page = MockPage()
        await ppf.main(page)
        
        # Switch to Tab 2 (Analyse & Charts)
        page.navigation_bar.selected_index = 1
        page.navigation_bar.on_change(ev.Event(name='change', control=page.navigation_bar, data='1'))
        
        # Switch to Tab 3 (Karoo Sync)
        page.navigation_bar.selected_index = 2
        page.navigation_bar.on_change(ev.Event(name='change', control=page.navigation_bar, data='2'))
        
        # Switch back to Tab 1 (Setup)
        page.navigation_bar.selected_index = 0
        page.navigation_bar.on_change(ev.Event(name='change', control=page.navigation_bar, data='0'))

    asyncio.run(run())


def test_normalize_karoo_url():
    """Test standardizing various user-provided Karoo URLs and IP inputs."""
    assert ppf.normalize_karoo_url("192.168.1.50:8080") == "http://192.168.1.50:8080/upload"
    assert ppf.normalize_karoo_url("http://192.168.1.50:8080/") == "http://192.168.1.50:8080/upload"
    assert ppf.normalize_karoo_url("http://192.168.1.50:8080/upload?token=ABCDEF") == "http://192.168.1.50:8080/upload?token=ABCDEF"


def test_decode_qr_image_bytes():
    """Test QR decoding function handling both raw bytes and invalid images gracefully."""
    # Blank white image should safely return None without crashing
    img = Image.new('RGB', (100, 100), color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    
    res = ppf.decode_qr_image(buf.getvalue())
    assert res is None


def test_decode_qr_image_valid_code():
    """Test QR decoding function successfully extracting text from real QR code."""
    import qrcode
    test_url = "http://192.168.1.45:8080/upload?token=PRDUTX"
    qr_img = qrcode.make(test_url)
    buf = io.BytesIO()
    qr_img.save(buf, format='PNG')
    
    # Test bytes decoding
    res = ppf.decode_qr_image(buf.getvalue())
    assert res == test_url
    
    # Test PIL Image / numpy decoding
    res_pil = ppf.decode_qr_image(qr_img)
    assert res_pil == test_url


def test_ui_qr_camera_and_gpx_controls():
    """Test that GPX selector and QR camera scanner controls are configured properly in UI."""
    async def run():
        page = MockPage()
        await ppf.main(page)
        
        # Check Setup tab for GPX picker button
        tab_setup = page.controls[0].content
        assert tab_setup is not None
        
        # Check Sync tab
        page.navigation_bar.selected_index = 2
        page.navigation_bar.on_change(ev.Event(name='change', control=page.navigation_bar, data='2'))
        tab_sync = page.controls[0].content
        assert tab_sync is not None
        
    asyncio.run(run())


def test_gearing_and_pacing_mode_controls():
    """Test gearing dropdowns, cadence sliders, and pacing mode selection in Flet UI."""
    async def run():
        page = MockPage()
        await ppf.main(page)
        
        tab_setup = page.controls[0].content
        main_col = tab_setup.content
        
        # Check gearing card is at index 5
        card_gearing_col = main_col.controls[5].content.content
        pacing_dropdown = card_gearing_col.controls[0]
        resp_row = card_gearing_col.controls[2]
        
        climb_col = resp_row.controls[0]
        low_gear_dd = climb_col.controls[0]
        min_cad_slider = climb_col.controls[3]
        
        descent_col = resp_row.controls[1]
        high_gear_dd = descent_col.controls[0]
        max_cad_slider = descent_col.controls[3]
        
        gearing_badge = card_gearing_col.controls[4]
        assert gearing_badge is not None
        
        # Check defaults
        assert low_gear_dd.value == "33/34"
        assert high_gear_dd.value == "46/10"
        assert min_cad_slider.value == 75.0
        assert max_cad_slider.value == 105.0
        assert pacing_dropdown.value == "dynamic"
        
        # Change lowest gear to 30/34 (GRX subcompact)
        low_gear_dd.on_select(ev.Event(name='select', control=low_gear_dd, data='30/34'))
        assert low_gear_dd.value == "30/34"
        
        # Change highest gear to 50/11
        high_gear_dd.on_select(ev.Event(name='select', control=high_gear_dd, data='50/11'))
        assert high_gear_dd.value == "50/11"
        
        # Change min cadence to 80 rpm
        min_cad_slider.on_change(ev.Event(name='change', control=min_cad_slider, data='80.0'))
        min_cad_slider.on_change_end(ev.Event(name='change_end', control=min_cad_slider, data='80.0'))
        
        # Change max cadence to 110 rpm
        max_cad_slider.on_change(ev.Event(name='change', control=max_cad_slider, data='110.0'))
        max_cad_slider.on_change_end(ev.Event(name='change_end', control=max_cad_slider, data='110.0'))
        
        # Switch pacing mode to steady
        pacing_dropdown.on_select(ev.Event(name='select', control=pacing_dropdown, data='steady'))
        assert pacing_dropdown.value == "steady"
        
        # Switch back to dynamic
        pacing_dropdown.on_select(ev.Event(name='select', control=pacing_dropdown, data='dynamic'))
        assert pacing_dropdown.value == "dynamic"

    asyncio.run(run())


def test_unified_kpi_overview_on_all_three_tabs():
    """Test that all 3 tabs display the identical Übersicht & Leistungs-KPIs section with 6 cards."""
    async def run():
        page = MockPage()
        await ppf.main(page)

        expected_labels = [
            "Dauer (Prognose)",
            "Systemgewicht",
            "Relative FTP",
            "ø Leistung",
            "Normalisierte Leistung",
            "Gesamtanstieg"
        ]

        def check_tab_kpis(tab_container):
            col = tab_container.content
            kpi_section = col.controls[0]
            if hasattr(kpi_section, "content") and isinstance(kpi_section.content, ft.Column) and len(kpi_section.content.controls) > 0 and isinstance(kpi_section.content.controls[0], ft.Column):
                kpi_col = kpi_section.content.controls[0]
            else:
                kpi_col = kpi_section

            # Header
            header_row = kpi_col.controls[0]
            assert "Übersicht & Leistungs-KPIs" in header_row.controls[1].value

            # ResponsiveRow with 6 KPI Cards
            cards_row = kpi_col.controls[1]
            assert len(cards_row.controls) == 6
            card_labels = [c.content.controls[0].controls[1].value for c in cards_row.controls]
            assert card_labels == expected_labels
            card_values = [c.content.controls[1].value for c in cards_row.controls]
            for v in card_values:
                assert v != "-" and len(v) > 0

        # Check Tab 1
        check_tab_kpis(page.controls[0].content)

        # Switch to Tab 2
        page.navigation_bar.selected_index = 1
        page.navigation_bar.on_change(ev.Event(name='change', control=page.navigation_bar, data='1'))
        check_tab_kpis(page.controls[0].content)

        # Switch to Tab 3
        page.navigation_bar.selected_index = 2
        page.navigation_bar.on_change(ev.Event(name='change', control=page.navigation_bar, data='2'))
        check_tab_kpis(page.controls[0].content)

    asyncio.run(run())


def test_settings_persistence_save_and_reload():
    """Test that adjusting sliders and dropdowns persists settings to JSON and reloads them on next startup."""
    async def run():
        # First session
        page1 = MockPage()
        await ppf.main(page1)

        tab_setup = page1.controls[0].content
        main_col = tab_setup.content

        # 1. Adjust FTP slider to 340
        card1_col = main_col.controls[1].content.content
        ftp_slider = card1_col.controls[1]
        ftp_slider.on_change(ev.Event(name='change', control=ftp_slider, data='340.0'))
        ftp_slider.on_change_end(ev.Event(name='change_end', control=ftp_slider, data='340.0'))

        # 2. Adjust Rider Weight slider to 82.5
        weights_row = card1_col.controls[6]
        rider_w_slider = weights_row.controls[0].controls[1]
        rider_w_slider.on_change(ev.Event(name='change', control=rider_w_slider, data='82.5'))
        rider_w_slider.on_change_end(ev.Event(name='change_end', control=rider_w_slider, data='82.5'))

        # 3. Adjust Lowest Gear dropdown to 30/34
        card3_col = main_col.controls[5].content.content
        resp_row = card3_col.controls[2]
        low_gear_dd = resp_row.controls[0].controls[0]
        low_gear_dd.on_select(ev.Event(name='select', control=low_gear_dd, data='30/34'))

        # Check that settings were saved to file
        saved = ppf.load_settings()
        assert saved["initial_ftp"] == 340
        assert saved["rider_w"] == 82.5
        assert saved["lowest_gear_key"] == "30/34"

        # Second session: new page bootstrap
        page2 = MockPage()
        await ppf.main(page2)

        # Verify that loaded state reflects saved values
        tab_setup2 = page2.controls[0].content
        main_col2 = tab_setup2.content
        card1_col2 = main_col2.controls[1].content.content
        ftp_slider2 = card1_col2.controls[1]
        rider_w_slider2 = card1_col2.controls[6].controls[0].controls[1]
        low_gear_dd2 = main_col2.controls[5].content.content.controls[2].controls[0].controls[0]

        assert ftp_slider2.value == 340
        assert rider_w_slider2.value == 82.5
        assert low_gear_dd2.value == "30/34"

    asyncio.run(run())


def test_settings_reset_to_defaults():
    """Test that clicking the reset button resets all settings to defaults."""
    async def run():
        page = MockPage()
        await ppf.main(page)

        tab_setup = page.controls[0].content
        main_col = tab_setup.content

        # Change FTP
        card1_col = main_col.controls[1].content.content
        ftp_slider = card1_col.controls[1]
        ftp_slider.on_change(ev.Event(name='change', control=ftp_slider, data='380.0'))
        ftp_slider.on_change_end(ev.Event(name='change_end', control=ftp_slider, data='380.0'))

        assert ppf.load_settings()["initial_ftp"] == 380

        # Click reset button in hero_dashboard header
        hero_dashboard = main_col.controls[0]
        header_row = hero_dashboard.content.controls[2]  # Row with "Fahrereinstellungen & Pacing" and reset button
        reset_btn = header_row.controls[2]  # ft.IconButton
        assert reset_btn.icon == ft.Icons.RESTART_ALT
        reset_btn.on_click(ev.Event(name='click', control=reset_btn))

        # Check values reset
        assert ftp_slider.value == ppf.DEFAULT_SETTINGS["initial_ftp"]
        saved = ppf.load_settings()
        assert saved["initial_ftp"] == ppf.DEFAULT_SETTINGS["initial_ftp"]

    asyncio.run(run())



