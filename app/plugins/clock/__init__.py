from app.plugins.clock.commands import handle_time
from app.plugins.clock.tools import get_current_time
from app.plugins.contracts import PluginCommand, ToolPlugin

# Named "clock" rather than "time" so that `import time` inside this
# package's own modules is unambiguous to a reader. Python 3 resolves it
# to the standard library either way; the confusion is the cost.
PLUGIN = ToolPlugin(
    name="clock",
    factory=lambda _context: [get_current_time],
    description="get_current_time — current date and time in Japan (JST)",
    commands=(
        PluginCommand(
            namespace="time",
            handler=handle_time,
            help_text="/time — current date and time in Japan (JST), no LLM call",
        ),
    ),
)
