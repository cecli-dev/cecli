from textual.app import App, ComposeResult

from cecli.tui.widgets.footer import MainFooter
from cecli.tui.widgets.input_container import InputContainer


class FooterApp(App):
    def compose(self) -> ComposeResult:
        yield MainFooter(id="footer")


class PollingInputContainer(InputContainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.poll_count = 0

    def _refresh_sub_agents(self):
        self.poll_count += 1
        super()._refresh_sub_agents()


class InputContainerApp(App):
    def compose(self) -> ComposeResult:
        yield PollingInputContainer(coder_mode="agent", id="input-container")


async def test_reduced_motion_footer_uses_static_activity_indicator():
    app = FooterApp()
    app.animation_level = "none"

    async with app.run_test():
        footer = app.query_one(MainFooter)
        footer.start_spinner("Working")

        assert footer._spinner_interval is None
        assert footer.render().plain.startswith("• Working")


async def test_reduced_motion_keeps_subagent_polling_without_alternating_icons():
    app = InputContainerApp()
    app.animation_level = "none"

    async with app.run_test() as pilot:
        container = app.query_one(PollingInputContainer)
        container.show_squares = False

        await pilot.pause(1.1)

        assert container.poll_count >= 1
        assert container.show_squares is False
